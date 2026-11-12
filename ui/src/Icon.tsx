const paths: Record<string, string> = {
  grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  shield: "M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6z M8.5 12l2.5 2.5 4.5-5",
  arrow: "M5 12h14 M14 7l5 5-5 5",
  check: "M5 12l4 4L19 6",
  document: "M14 2H5v20h14V7z M14 2v6h5 M8 12h8 M8 16h6",
  box: "M3 7l9-4 9 4v10l-9 4-9-4z M3 7l9 4 9-4 M12 11v10 M7 5l9 4",
  spark: "m12 3 2.6 6.4L21 12l-6.4 2.6L12 21l-2.6-6.4L3 12l6.4-2.6z",
  clock: "M12 8v5l3 2 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
  lock: "M6 10h12v11H6z M8 10V6a4 4 0 0 1 8 0v4",
  external: "M14 3h7v7 M10 14 21 3 M10 4H4v16h16v-6",
  refresh: "M20 8a9 9 0 1 0 0 8 M20 3v5h-5",
  down: "M12 3v12 M7 10l5 5 5-5 M4 17v4h16v-4",
  alert: "M12 3 2 21h20z M12 9v5 M12 17v1",
  user: "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0 M4 21v-2a8 8 0 0 1 16 0v2",
  pin: "M19 9c0 5-7 12-7 12S5 14 5 9a7 7 0 0 1 14 0 M14 9a2 2 0 1 1-4 0 2 2 0 0 1 4 0",
  chevron: "m9 5 7 7-7 7",
  close: "m6 6 12 12 M18 6 6 18",
};
export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name] || paths.shield} />
    </svg>
  );
}
