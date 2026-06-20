import { useTheme } from './ThemeProvider.jsx';
import { Sun, Moon } from 'lucide-react';
import './theme-toggle.css';

const ThemeToggle = () => {
  const { theme, toggleTheme } = useTheme();

  return (
    <button onClick={toggleTheme} className="theme-toggle">
      {theme === 'light' ? <Moon size={24} color="#221f2c" fill="#221f2c" className="moon" />
      : <Sun size={24} color="#221f2c" fill="#221f2c" className="sun" />}
    </button>
  );
};

export default ThemeToggle;