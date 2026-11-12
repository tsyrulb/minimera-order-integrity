import { Buyer } from "./Buyer";
import { Merchant } from "./Merchant";

export function App() {
  const path = window.location.pathname;
  if (path.startsWith("/buyer/") || path === "/return") return <Buyer />;
  return <Merchant />;
}
