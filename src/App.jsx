import { useEffect} from "react";
import { useTheme } from './components/ThemeProvider.jsx';
import Header from './components/Header.jsx';
import ItemList from './components/CraftingList.jsx';

function App() {
  const { theme } = useTheme();

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  return (
    <div className="app">
      <Header />
      <ItemList />
    </div>
  );
};

export default App;