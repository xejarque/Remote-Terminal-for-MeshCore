import './utils/meshcoreDecoderPatch';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import './index.css';
import './themes.css';
import './styles.css';
import { getSavedTheme, applyTheme } from './utils/theme';

// Apply saved theme before first render
applyTheme(getSavedTheme());

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
