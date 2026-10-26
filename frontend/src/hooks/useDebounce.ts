import { useEffect, useState } from 'react';

export function useDebounce<T>(value: T, delay = 400): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => {
      try {
        if (typeof window !== 'undefined') {
          setDebounced(value);
        }
      } catch {
        // Ignore unmounted environment tear-down in tests
      }
    }, delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

export function useDebouncedValue<T>(value: T, delay = 400): T {
  return useDebounce(value, delay);
}
