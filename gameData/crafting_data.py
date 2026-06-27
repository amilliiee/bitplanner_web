import copy
import json
import os
import shutil
import sys
from pathlib import Path

# ---------------------
# --- CONFIGURATION ---
# ---------------------
# Data sourced from BitCraft ToolBox (https://github.com/BitCraftToolBox/BitCraft_GameData)
# Icons sourced Brico (https://github.com/BitCraftToolBox/brico)
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent

DATA_ROOT = PROJECT_ROOT / "gameData" / "BitCraft_GameData" / "static"
ICON_ROOT = PROJECT_ROOT / "gameData" / "BitCraft_Assets" / "sprites" / "GeneratedIcons"
OUTPUT_PATH = PROJECT_ROOT / "src" / "data" / "crafting_data.json"
PUBLIC_DEST_ICONS_PATH = PROJECT_ROOT / "public" / "assets" / "GeneratedIcons"

# Cargo offset: Shift value added to cargo ids to allow for items and cargo to exist in a single list
CARGO_OFFSET = 0xffffffff
# Ignored tags: Tags within item_desc.json that aren't needed for crafting
IGNORED_TAGS = [
  'DEVELOPER ITEM', 'Crushed Ore', 'Precious', 'Cosmetic Clothes',
  'Letter', 'Journal Page', 'Ancient Research'
]
# Skill ids: Id # that attaches a specific game skill to the crafting of the item
SKILL_IDS = list(range(1, 15))
# Order overrides: Orders recipes that use carvings before recipes that use diagrams
RECIPES_ORDER_OVERRIDES = {
  1210004: [1210037, 1210038],
  2210004: [2210037, 2210038],
  3210004: [3210037, 3210038],
  4210004: [4210037, 4210038],
  5210004: [5210037, 5210038],
  6210004: [6210037, 6210038]
}
# Overrides by tags: Key is paired with all item types that are used to craft key type
RECIPES_ORDER_OVERRIDES_BY_TAG = {
  'Fertilizer': ['Berry', 'Flower', 'Lake Fish Filet', 'Oceanfish Filet', 'Raw Meat', 'Food Waste'],
  'Catalyst': ['Grain Seeds', 'Filament Seeds', 'Vegetable Seeds']
}

RARITY_MAP = {
  'Common': 1, 'Uncommon': 2, 'Rare': 3, 'Epic': 4, 'Legendary': 5
}

# ---------------------------
# --- GLOBAL DATA STORAGE ---
# ---------------------------
class GameData:
  """Holds all loaded game data to avoid passing it through every function."""
  cargo = []
  crafting_recipes = []
  enemies = []
  extraction_recipes = []
  items = []
  item_conversions = []
  item_lists = []

# -------------------------
# --- UTILITY FUNCTIONS ---
# -------------------------
def load_json(filepath):
  try:
    with open(filepath, 'r', encoding='utf-8') as f:
      return json.load(f)
  except FileNotFoundError:
    print(f"FATAL: Could not find {filepath}")
    sys.exit(1)
  except json.JSONDecodeError as e:
    print(f"FATAL: Invalid JSON in {filepath}: {e}")
    sys.exit(1)
    
#

def rarity_to_number(rarity_str):
  return RARITY_MAP.get(rarity_str, 1)

#

def find_recipes(item_id, is_cargo=False, direction='both'):
  """
  Find crafting recipes involving an item.

  Args:
      item_id: The numeric id of the item/cargo
      is_cargo: True if querying cargo, as item_type values are different
      direction: 'Producing', 'consuming', or 'both'
                  - producing: this item is OUTPUT (crafted from materials)
                  - consuming: this item is INPUT (used as material)
                  
  Returns:
      list of recipe dicts with keys:
        'level_requirements', 'consumed_items', 'output_quantity', 'possibilities', 'type'
  """
  expected_type = "Cargo" if is_cargo else "Item"
  recipes = []
  
  for recipe in GameData.crafting_recipes:
    output_match = False
    input_match = False
    
    # Check if item is produced
    for result in recipe['crafted_item_stacks']:
      if result['item_id'] == item_id and result['item_type'] == expected_type:
        output_match = True
        break
      
    # Check if item is consumed
    for consumed in recipe['consumed_item_stacks']:
      if consumed['item_id'] == item_id and consumed['item_type'] == expected_type:
        input_match = True
        break
    
    # Skip self consumption to be safe
    consumes_itself = any(c['item_id'] == item_id for c in recipe['consumed_item_stacks'])
    if consumes_itself:
      continue
    
    # Determine direction to include
    include_producing = output_match and direction in ['producing', 'both']
    include_consuming = input_match and direction in ['consuming', 'both']
    if not (include_producing or include_consuming):
      continue
    
    # Build consumption list for recipe
    consumed_items = []
    for consumed in recipe['consumed_item_stacks']:
      if consumes_itself and consumed['item_id'] == item_id:
        continue
      cid = consumed['item_id'] + (CARGO_OFFSET if consumed['item_type'] == 'Cargo' else 0)
      consumed_items.append({ 'id': cid, 'quantity': consumed['quantity'] })
      
    if direction == 'both':
      # Add recipe twice with different metadata
      if include_producing:
        recipes.append({
          'level_requirements': recipe['level_requirements'][0] if recipe['level_requirements'] else {},
          'consumed_items': consumed_items,
          'output_quantity': next((r['quantity'] for r in recipe['crafted_item_stacks'] 
                                  if r['item_id'] == item_id and r['item_type'] == expected_type), 1),
          'possibilities': {},
          'role': 'producer' # This recipe CREATES the item
        })
      if include_consuming:
        recipes.append({
          'level_requirements': recipe['level_requirements'][0] if recipe['level_requirements'] else {},
          'consumed_items': [c for c in consumed_items if c['id'] != item_id], # Remove self-reference if it exists
          'output_quantity': next((r['quantity'] for r in recipe['crafted_item_stacks']), 1),
          'possibilities': {},
          'role': 'consumer' # This recipe CONSUMES the item
        })
    elif direction == 'producing':
      recipes.append({
          'level_requirements': recipe['level_requirements'][0] if recipe['level_requirements'] else {},
          'consumed_items': consumed_items,
          'output_quantity': next((r['quantity'] for r in recipe['crafted_item_stacks'] 
                                  if r['item_id'] == item_id and r['item_type'] == expected_type), 1),
          'possibilities': {},
          'role': 'producer'
        })
    else: # Consuming
      recipes.append({
          'level_requirements': recipe['level_requirements'][0] if recipe['level_requirements'] else {},
          'consumed_items': [c for c in consumed_items if c['id'] != item_id], # Remove self-reference if it exists
          'output_quantity': next((r['quantity'] for r in recipe['crafted_item_stacks']), 1),
          'possibilities': {},
          'role': 'consumer'
        })
  return recipes

#

def find_extraction_skill(item_id, is_cargo=False):
  """
  Find which skill is required to extract this item. Searches both extraction AND enemy drops.
  Returns skill ID if found, or -1 if not extractable.

  Rarely queries extraction 'consuming' since most extraction recipes are 'producing'.
  """
  expected_type = "Cargo" if is_cargo else "Item"
  
  # Check extraction recipes
  for recipe in GameData.extraction_recipes:
    for result_group in recipe['extracted_item_stacks']:
      result = result_group['item_stack']
      if result['item_id'] == item_id and result['item_type'] == expected_type:
        return recipe['level_requirements'][0]['skill_id']
      
  # Check enemy drops
  for enemy in GameData.enemies:
    for result_group in enemy['extracted_item_stacks']:
      result = result_group['item_stack']
      if result['item_id'] == item_id and result['item_type'] == expected_type:
        return enemy['experience_per_damage_dealt'][0]['skill_id']
  
  return -1 # Not extractable by any skill

#

def get_recipe_priority(target_id, recipe):
  """Calculate display priority for recipe ordering."""
  # Override priorities (carvings before diagrams)
  if target_id in RECIPES_ORDER_OVERRIDES.keys():
    for item in recipe['consumed_items']:
      if item['id'] in RECIPES_ORDER_OVERRIDES[target_id]:
        return RECIPES_ORDER_OVERRIDES[target_id].index(item['id'])
      
  target_tag = CRAFTING_DATA[target_id]['tag']
  if target_tag in RECIPES_ORDER_OVERRIDES_BY_TAG:
    for item in recipe['consumed_items']:
      if item['id'] not in CRAFTING_DATA:
        continue
      if item['id'] in CRAFTING_DATA:
        consumed_item_tag = CRAFTING_DATA[item['id']]['tag']
        if consumed_item_tag in RECIPES_ORDER_OVERRIDES_BY_TAG[target_tag]:
          return RECIPES_ORDER_OVERRIDES_BY_TAG[target_tag].index(consumed_item_tag)
        
  priority_bonus = 0
  if 'Tool' in target_tag:
    for item in recipe['consumed_items']:
      if item['id'] not in CRAFTING_DATA:
        continue
      if CRAFTING_DATA[item['id']]['tag'] == 'Scrap':
        priority_bonus += 10000
        break
      
  # Default formula
  if not recipe['consumed_items']:
    return 999999
  
  item = recipe['consumed_items'][0]
  item_id = item['id']
  
  if item_id not in CRAFTING_DATA:
    return 999999
  
  item_qty = item['quantity']
  item_rarity = CRAFTING_DATA[item_id]['rarity']
  output_qty = recipe['output_quantity']
  try:
    return (item_qty + (1000 if item_id > CARGO_OFFSET else 0)) \
      * item_rarity * 100 / output_qty \
        + sum(map(int, str(item_id))) + priority_bonus
  except (TypeError, ZeroDivisionError) as e:
    print(f"WARNING: Could not calculate priority for {target_id}, recipe {recipe.get('name', 'unknown')}. Using default priority. Error: {e}")
    return 999999 # Return high number (low priority) so recipe is sorted to end but script doesn't crash

#

def process_items():
  """Load all items from item_desc.json into CRAFTING_DATA."""
  print('Processing items...')
  
  for item in GameData.items:
    id = item['id']
    
    if id > CARGO_OFFSET:
      print(f"FATAL: Item ID {id} exceeds uint32 range.")
      sys.exit(1)

    ignore_item = any(tag in item['tag'] for tag in IGNORED_TAGS)
    if ignore_item:
      continue
    
    CRAFTING_DATA[id] = {
      'name': item['name'],
      'tier': item['tier'],
      'rarity': rarity_to_number(item['rarity']),
      'icon': 'assets/' + item['icon_asset_name'],
      'recipes': find_recipes(id),
      'extraction_skill': find_extraction_skill(id),
      'tag': item['tag']
    }
    all_craftable_items.add(id)

#

def process_cargo():
  print('Processing cargo...')
  for item in GameData.cargo:
    id = item['id']
    if id > CARGO_OFFSET:
      print(f"FATAL: Item ID {id} exceeds uint32 range.")
      sys.exit(1)
    
    CRAFTING_DATA[CARGO_OFFSET + id] = {
      'name': item['name'],
      'tier': item['tier'],
      'rarity': rarity_to_number(item['rarity']),
      'icon': 'assets/' + item['icon_asset_name'],
      'recipes': find_recipes(id, True),
      'extraction_skill': find_extraction_skill(id, True),
      'tag': item['tag']
    }
    all_craftable_items.add(id)

#

def consolidate_icons():
  """Copy icons from source repo to public/assets/GeneratedIcons."""
  SOURCE_ICONS_PATH = ICON_ROOT
  print(f"Copying icons from {SOURCE_ICONS_PATH} to {PUBLIC_DEST_ICONS_PATH}...")
  
  PUBLIC_DEST_ICONS_PATH.mkdir(parents=True, exist_ok=True)
  copied_count = 0
  
  if SOURCE_ICONS_PATH.exists():
    for root, _, files in os.walk(SOURCE_ICONS_PATH):
      for file in files:
        if file.endswith('.webp'):
          src_file = Path(root) / file
          # Calculate relative path from SOURCE to preserve subfolder structure
          rel_path = src_file.relative_to(SOURCE_ICONS_PATH)
          dst_file = PUBLIC_DEST_ICONS_PATH / rel_path
          
          # Create destination subfolder if DNE
          dst_file.parent.mkdir(parents=True, exist_ok=True)
          
          shutil.copy2(src_file, dst_file)
          copied_count += 1
          
    print(f"Copied {copied_count} icons with subfolder structure preserved.")
  else:
    print(f"  ERROR: Source path does not exist!")
    print(f"  Checking parent: {SOURCE_ICONS_PATH.parent.exists()}")
    if SOURCE_ICONS_PATH.parent.exists():
      print(f"  Parent contents: {[str(i) for i in SOURCE_ICONS_PATH.parent.iterdir()]}")

#

def normalize_icons():
  """Verify icon files exist at expected paths and update JSON data."""
  print('Normalizing icon paths...')
  missing_icons = []
  
  for item_id, item_data in CRAFTING_DATA.items():
    og_icon = item_data['icon']
    
    if not og_icon or og_icon == 'Unknown':
      continue
    
    # Clean brackets/extension from icon path
    clean_icon = os.path.splitext(og_icon.split('[')[0])[0]
    
    # Construct absolute path to copied file
    full_path = PUBLIC_DEST_ICONS_PATH / f"{clean_icon}.webp"
    
    if not full_path.exists():
      missing_icons.append(og_icon)
      item_data['icon'] = 'Unknown'
    else:
      # Store path relative to public/ so React can access
      rel_path = full_path.relative_to(PROJECT_ROOT / "public")
      item_data['icon'] = rel_path.as_posix().replace('\\', '/')
      
  if missing_icons:
    print("Missing icons found:")
    for m in sorted(set(missing_icons))[:5]:
      print(f"  - {m}")
    if len(missing_icons) > 5:
      print(f"  ...and {len(missing_icons) - 5} more")
  else:
    print('All icons verified.')

#

def organize_recipes():
  """Handle bundle logic: delete base items and redistribute recipes to targets."""
  print('Reorganizing recipes...')
  
  valid_bundle_ids = {ilist['id'] for ilist in GameData.item_lists if ilist['id'] != 0}
  try:
    for item in GameData.items:
      if item['tag'] == 'Crushed Ore': continue
      id = item['id']
      list_id = item['item_list_id']
      
      if list_id == 0 or list_id not in valid_bundle_ids:
        continue
      
      if id in CRAFTING_DATA:
        del CRAFTING_DATA[id]
        
      for item_list in GameData.item_lists:
        if item_list['id'] != list_id: continue
        
        possible_recipes = {}
        
        for possibility in item_list['possibilities']:
          chance = possibility['probability']
          for result in possibility['items']:
            target_id = result['item_id'] + (CARGO_OFFSET if result['item_type'] == 'Cargo' else 0)
            
            if target_id not in CRAFTING_DATA: continue
            
            if CRAFTING_DATA[target_id]['extraction_skill'] < 0:
              is_target_cargo = (target_id > CARGO_OFFSET)
              CRAFTING_DATA[target_id]['extraction_skill'] = find_extraction_skill(id, is_target_cargo)
              
            if target_id not in possible_recipes:
              possible_recipes[target_id] = {}
            qty = result['quantity']
            if qty not in possible_recipes[target_id]:
              possible_recipes[target_id][qty] = 0.0
            possible_recipes[target_id][qty] += chance
            
        recipes = find_recipes(id)
        for target_id, possibilities in possible_recipes.items():
          filtered = [copy.deepcopy(r) for r in recipes if not any (ci['id'] == target_id for ci in r['consumed_items'])]
          
          new_recipes = copy.deepcopy(filtered)
          for r in new_recipes:
            r['possibilities'] = possibilities.copy()
          CRAFTING_DATA[target_id]['recipes'].extend(new_recipes)
  except Exception as e:
    print(f"ERROR during reorganization: {e}")
    import traceback
    traceback.print_exc() 

#

def sort_recipes():
  """Deduplicate recipes and sort by priority."""
  print('Sorting and cleaning up recipes...')
  
  for key, value in CRAFTING_DATA.items():
    recipes = value['recipes']
    dedup = {json.dumps(r, sort_keys=True) for r in recipes}
    value['recipes'] = [json.loads(r) for r in dedup]
    value['recipes'].sort(key=lambda r: get_recipe_priority(key, r))

#

def filter_empty_entries():
  """Remove items with no recipes, extraction, and no recipe-item status."""
  print('Final filtering of empty entries...')
  
  to_remove = []
  for key, value in CRAFTING_DATA.items():
    has_recipes = len(value['recipes']) > 0
    has_extraction = value['extraction_skill'] != -1
    is_recipe_item = any(s in value['name'] for s in ['Recipe:', 'Diagram', 'Carvings'])
    
    if not (has_recipes or has_extraction or is_recipe_item):
      to_remove.append(key)
      
  for key in to_remove:
    del CRAFTING_DATA[key]
    
  print(f"Kept {len(CRAFTING_DATA)} entries after filtering.")
  
# -------------------------
# --------- MAIN ----------
# -------------------------
def main():
  print('Starting data pipeline...')
  
  # Load data
  GameData.cargo = load_json(DATA_ROOT / 'cargo_desc.json')
  GameData.crafting_recipes = load_json(DATA_ROOT / 'crafting_recipe_desc.json')
  GameData.enemies = load_json(DATA_ROOT / 'enemy_desc.json')
  GameData.extraction_recipes = load_json(DATA_ROOT / 'extraction_recipe_desc.json')
  GameData.items = load_json(DATA_ROOT / 'item_desc.json')
  GameData.item_lists = load_json(DATA_ROOT / 'item_list_desc.json')
  
  global CRAFTING_DATA
  CRAFTING_DATA = {}
  global all_craftable_items
  all_craftable_items = set()
  
  process_items()
  process_cargo()
  
  consolidate_icons()
  #normalize_icons()
  
  organize_recipes()
  sort_recipes()
  filter_empty_entries()
  
  # Save output
  OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
  print(f"Saving to {OUTPUT_PATH}...")
  with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(CRAFTING_DATA, f, indent=2)
  print(f"Success! Generated {len(CRAFTING_DATA)} unique entries.")
  
if __name__ == "__main__":
  main()
  if 'GITHUB_ACTIONS' not in os.environ:
    input('Press Enter to exit...')