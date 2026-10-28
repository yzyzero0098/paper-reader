import { useCallback, useEffect, useState } from "react";
import { Route, Routes } from "react-router-dom";
import { api } from "./api";
import type { Settings } from "./types";
import Library from "./pages/Library";
import Reader from "./pages/Reader";
import SettingsModal from "./components/SettingsModal";

export default function App() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [showSettings, setShowSettings] = useState(false);

  const reload = useCallback(() => api.settings().then(setSettings).catch(() => {}), []);
  useEffect(() => {
    reload();
  }, [reload]);

  return (
    <>
      <Routes>
        <Route path="/" element={<Library settings={settings} onOpenSettings={() => setShowSettings(true)} />} />
        <Route
          path="/paper/:id"
          element={<Reader settings={settings} onOpenSettings={() => setShowSettings(true)} onSettingsChanged={setSettings} />}
        />
      </Routes>
      {showSettings && (
        <SettingsModal
          onClose={() => {
            setShowSettings(false);
            reload();
          }}
        />
      )}
    </>
  );
}
