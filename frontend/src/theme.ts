import { useEffect, useState } from "react";

/** "system" follows the OS setting. Stored per browser. */
export type ThemePref = "system" | "light" | "dark";

const THEME_KEY = "paper-reader.theme";
const PDF_KEY = "paper-reader.pdfDark";
const EVENT = "paper-reader-theme";

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode: the choice just isn't remembered */
  }
}

export function getThemePref(): ThemePref {
  const v = read(THEME_KEY);
  return v === "light" || v === "dark" ? v : "system";
}

export function getPdfDark(): boolean {
  return read(PDF_KEY) === "1";
}

const media = () => window.matchMedia?.("(prefers-color-scheme: dark)");

export function resolveTheme(pref: ThemePref): "light" | "dark" {
  if (pref === "system") return media()?.matches ? "dark" : "light";
  return pref;
}

/** Put the current choice on <html> (data-theme, data-pdf). */
export function applyTheme() {
  const root = document.documentElement;
  root.dataset.theme = resolveTheme(getThemePref());
  root.dataset.pdf = getPdfDark() ? "dark" : "light";
}

export function setThemePref(pref: ThemePref) {
  write(THEME_KEY, pref);
  applyTheme();
  window.dispatchEvent(new Event(EVENT));
}

export function setPdfDark(on: boolean) {
  write(PDF_KEY, on ? "1" : "0");
  applyTheme();
  window.dispatchEvent(new Event(EVENT));
}

/** Current preference, resolved theme and PDF option; re-renders on any change (incl. OS switch). */
export function useTheme() {
  const snapshot = () => ({ pref: getThemePref(), resolved: resolveTheme(getThemePref()), pdfDark: getPdfDark() });
  const [state, setState] = useState(snapshot);
  useEffect(() => {
    const update = () => {
      applyTheme();
      setState(snapshot());
    };
    const mq = media();
    mq?.addEventListener?.("change", update);
    window.addEventListener(EVENT, update);
    window.addEventListener("storage", update);
    return () => {
      mq?.removeEventListener?.("change", update);
      window.removeEventListener(EVENT, update);
      window.removeEventListener("storage", update);
    };
  }, []);
  return state;
}
