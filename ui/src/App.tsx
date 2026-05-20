import { SessionsPage } from "./pages/SessionsPage";
import { ToastProvider } from "./components/ToastProvider";

export default function App(): JSX.Element {
  return (
    <ToastProvider>
      <SessionsPage />
    </ToastProvider>
  );
}
