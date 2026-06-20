import { useEffect} from "react";
import { useTheme } from './ThemeProvider.jsx';
import Header from './Header.jsx';

function App() {
  const { theme } = useTheme();

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  return (
    <div className="app">
      <Header />
      
    </div>
  );
};

export default App;