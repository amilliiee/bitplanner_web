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
DATA_ROOT = Path("BitCraft_GameData/static")
ICON_ROOT = Path("BitCraft_Assets/sprites/GeneratedIcons")
OUTPUT_PATH = Path("../src/data/crafting_data.json")

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
    
# # # # # # # # # # # # # # # # # # # # # # # #
    
def rarity_to_number(rarity_str):
  return RARITY_MAP.get(rarity_str, 1)

# # # # # # # # # # # # # # # # # # # # # # # #

def find_recipes(id, is_cargo=False):
  expected_type = "Cargo" if is_cargo else "Item"
  recipes = []
  
  for recipe in GameData.crafting_recipes:
    for result in recipe['crafted_item_stacks']:
      if result['item_id'] == id and result['item_type'] == expected_type:
        consumed_items = []
        consumes_itself = False
        
        for consumed_item in recipe['consumed_item_stacks']:
          if consumed_item['item_id'] == id:
            consumes_itself = True
            break
          
          consumed_id = consumed_item['item_id'] + (CARGO_OFFSET if consumed_item['item_type'] == 'Cargo' else 0)
          consumed_items.append({ 'id': consumed_id, 'quantity': consumed_item['quantity'] })
          
        if consumes_itself:
          continue
        
        recipe_data = {
          'level_requirements': recipe['level_requirements'][0],
          'consumed_items': consumed_items,
          'output_quantity': result['quantity'],
          'possibilities': {}
        }
        recipes.append(recipe_data)
  return recipes

# # # # # # # # # # # # # # # # # # # # # # # #

def find_extraction_skill(id, is_cargo=False):
  expected_type = "Cargo" if is_cargo else "Item"
  
  for recipe in GameData.extraction_recipes:
    for result_group in recipe['extracted_item_stacks']:
      result = result_group['item_stack']
      if result['item_id'] == id and result['item_type'] == expected_type:
        return recipe['level_requirements'][0]['skill_id']
      
  for enemy in GameData.enemies:
    for result_group in enemy['extracted_item_stacks']:
      result = result_group['item_stack']
      if result['item_id'] == id and result['item_type'] == expected_type:
        return enemy['experience_per_damage_dealt'][0]['skill_id']
  return -1 # Not found

# # # # # # # # # # # # # # # # # # # # # # # #

def get_recipe_priority(target_id, recipe):
  if target_id in RECIPES_ORDER_OVERRIDES.keys():
    for item in recipe['consumed_items']:
      if item['id'] in RECIPES_ORDER_OVERRIDES[target_id]:
        return RECIPES_ORDER_OVERRIDES[target_id].index(item['id'])
      
  target_tag = CRAFTING_DATA[target_id]['tag']
  if target_tag in RECIPES_ORDER_OVERRIDES_BY_TAG:
    for item in recipe['consumed_items']:
      if item['id'] not in CRAFTING_DATA:
        continue
      consumed_item_tag = CRAFTING_DATA[item['id']]['tag']
      if consumed_item_tag in RECIPES_ORDER_OVERRIDES_BY_TAG[target_tag]:
        return RECIPES_ORDER_OVERRIDES_BY_TAG[target_tag].index(consumed_item_tag)
      
  priority_bonus = 0
  if 'Tool' in target_tag:
    for consumed_item in recipe['consumed_items']:
      if consumed_item['id'] not in CRAFTING_DATA:
        continue
      if CRAFTING_DATA[consumed_item['id']]['tag'] == 'Scrap':
        priority_bonus += 10000
        break
      
  if not recipe['consumed_items']:
    return 999999
  
  item = recipe['consumed_items'][0]
  item_id = item['id']
  
  if item_id not in CRAFTING_DATA:
    return 999999
  
  item_rarity = CRAFTING_DATA[item_id]['rarity']
  item_quantity = item['quantity']
  try:
    return (item_quantity + (1000 if item_id > CARGO_OFFSET else 0)) \
      * item_rarity * 100 / recipe['output_quantity'] \
        + sum(map(int, str(item_id))) + priority_bonus
  except (TypeError, ZeroDivisionError) as e:
    print(f"WARNING: Could not calculate priority for {target_id}, recipe {recipe.get('name', 'unknown')}. Using default priority. Error: {e}")
    return 999999 # Return high number (low priority) so recipe is sorted to end but script doesn't crash


# # # # # # # # # # # # # # # # # # # # # # # #

def main():
  print("Starting data pipeline...")
  
  # Load data
  print('Loading static game data...')
  GameData.cargo = load_json(DATA_ROOT / 'cargo_desc.json')
  GameData.crafting_recipes = load_json(DATA_ROOT / 'crafting_recipe_desc.json')
  GameData.enemies = load_json(DATA_ROOT / 'enemy_desc.json')
  GameData.extraction_recipes = load_json(DATA_ROOT / 'extraction_recipe_desc.json')
  GameData.items = load_json(DATA_ROOT / 'item_desc.json')
  GameData.item_lists = load_json(DATA_ROOT / 'item_list_desc.json')
  
  global CRAFTING_DATA
  CRAFTING_DATA = {}
  all_craftable_items = set()
  
  # Process items
  print("Processing items...")
  total_items = len(GameData.items)
  
  for i, item in enumerate(GameData.items):
    id = item['id']
    
    if id > CARGO_OFFSET:
      print(f"FATAL: Item ID {id} exceeds uint32 range.")
      sys.exit(1)
      
    ignore_item = any(tag in item['tag'] for tag in IGNORED_TAGS)
    if ignore_item:
      continue
    
    recipes = find_recipes(id)
    extraction_skill = find_extraction_skill(id)
    
    is_craftable = len(recipes) > 0
    is_extractable = extraction_skill != -1
    is_recipe_item = any(s in item['name'] for s in ['Recipe', 'Diagram', 'Carvings'])
    
    if not (is_craftable or is_extractable or is_recipe_item):
      continue
    
    CRAFTING_DATA[id] = {
      'name': item['name'],
      'tier': item['tier'],
      'rarity': rarity_to_number(item['rarity']),
      'icon': item['icon_asset_name'],
      'recipes': recipes,
      'extraction_skill': extraction_skill,
      'tag': item['tag']
    }
    if is_craftable:
      all_craftable_items.add(id)
      
  # Process cargo
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
      'icon': item['icon_asset_name'],
      'recipes': find_recipes(id, True),
      'extraction_skill': find_extraction_skill(id, True),
      'tag': item['tag']
    }
  
  # Icon consolidation
  generated_icons_path = Path("brico/frontend/public/assets/GeneratedIcons")
  old_generated_icons_path = Path("brico/frontend/public/assets/OldGeneratedIcons")
  
  print("Consolidating icon directories...")
  
  # Scan directories
  generated_icons = set()
  if generated_icons_path.exists():
    for root, dirs, files in os.walk(generated_icons_path):
      for f in files:
        if f.endswith('.webp'):
          rel = os.path.relpath(os.path.join(root, f), generated_icons_path)
          generated_icons.add(rel)
  
  old_generated_icons = set()
  if old_generated_icons_path.exists():
    for root, dirs, files in os.walk(old_generated_icons_path):
      for f in files:
        if f.endswith('.webp'):
          rel = os.path.relpath(os.path.join(root, f), old_generated_icons_path)
          old_generated_icons.add(rel)
          
  missing_in_generated = old_generated_icons - generated_icons
  copied_count = 0
  
  for icon_path in missing_in_generated:
    src = old_generated_icons_path / icon_path
    dst = generated_icons_path / icon_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    copied_count += 1
    
  print(f"Copied {copied_count} missing icons.")
  
  # Normalize icon paths
  print('Normalizing icon paths...')
  missing_icons = []
  assets_root = Path('BitCraft_Assets/sprites/')
  
  for item_id, item_data in CRAFTING_DATA.items():
    icon = item_data['icon']
    
    # Strip path prefixes
    clean_icon = icon
    prefixes = ['GeneratedIcons/', 'OldGeneratedIcons/', 'Items/GeneratedIcons/', 'Cargo/GeneratedIcons/', 'Other/GeneratedIcons/']
    for prefix in prefixes:
      if prefix in clean_icon:
        clean_icon = clean_icon.split(prefix)[-1]
        
    # Remove brackets and content inside them    
    if '[' in clean_icon:
      clean_icon = clean_icon.split('[')[0]
    
    # Remove file extension
    clean_icon = os.path.splitext(clean_icon)[0]
    
    # Reconstruct proper path with GeneratedIcons/ prefix, check if icon should be in a subdirectory
    final_path = f"GeneratedIcons/{clean_icon}"
    full_path = assets_root / f"{final_path}.webp"
    
    if not full_path.exists():
      missing_icons.append(final_path)
      item_data['icon'] = 'Unknown'
    else:
      item_data['icon'] = final_path
      
  if missing_icons:
    print("Missing icons found:")
    for m in sorted(set(missing_icons))[:10]:
      print(f"   - {m}")
    if len(missing_icons) > 10:
      print(f"   ... and {len(missing_icons)-10} more")
  else:
    print("All icons verified.")
  
  # Reorganize recipes (bundle logic)
  print('Reorganizing recipes...')
  try:
    for item in GameData.items:
      if item['tag'] == 'Crushed Ore': continue
      id = item['id']
      list_id = item['item_list_id']
      
      if list_id == 0 or item['tier'] < 0: continue
      
      if id in CRAFTING_DATA:
        del CRAFTING_DATA[id]
      else:
        continue
      
      for item_list in GameData.item_lists:
        if item_list['id'] != list_id: continue
        
        possible_recipes = {}
        
        for possibility in item_list['possibilities']:
          chance = possibility['probability']
          for result in possibility['items']:
            target_id = result['item_id'] + (CARGO_OFFSET if result['item_type'] == "Cargo" else 0)
            
            if target_id not in CRAFTING_DATA: continue
            
            if CRAFTING_DATA[target_id]['extraction_skill'] < 0:
              is_target_cargo = (target_id > CARGO_OFFSET)
              CRAFTING_DATA[target_id]['extraction_skill'] = find_extraction_skill(id, is_target_cargo)
              
            if target_id not in possible_recipes: possible_recipes[target_id] = {}
            qty = result['quantity']
            if qty not in possible_recipes[target_id]: possible_recipes[target_id][qty] = 0.0
            possible_recipes[target_id][qty] += chance
            
        recipes = find_recipes(id)
        for target_id, possibilities in possible_recipes.items():
          filtered = [copy.deepcopy(r) for r in recipes if not any(ci['id'] == target_id for ci in r['consumed_items'])]
          
          new_recipes = copy.deepcopy(filtered)
          for r in new_recipes:
            r['possibilities'] = possibilities.copy()
            
          CRAFTING_DATA[target_id]['recipes'].extend(new_recipes)
        break
  except Exception as e:
    print(f"ERROR during reorganization: {e}")
    import traceback
    traceback.print_exc()  
  
  # Sort & cleanup
  print('Sorting and cleaning up recipes...')
  for key, value in CRAFTING_DATA.items():
    recipes = value['recipes']
    dedup = {json.dumps(r, sort_keys=True) for r in recipes}
    value['recipes'] = [json.loads(r) for r in dedup]
    value['recipes'].sort(key=lambda r: get_recipe_priority(key, r))
  
  # Save output
  OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
  print(f"Saving to {OUTPUT_PATH}...")
  with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(CRAFTING_DATA, f, indent=2)
    
  print(f"Success! Generated {len(CRAFTING_DATA)} unique entries.")

if __name__ == "__main__":
  main()
  input('Press Enter to exit...')