import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Home } from "./pages/Home";
import { Later } from "./pages/Later";
import { Projects } from "./pages/Projects";
import { Review } from "./pages/Review";
import { Settings } from "./pages/Settings";
import { Setup } from "./pages/Setup";
import { Traces } from "./pages/Traces";

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Projects />} />
      <Route path="/p/:pid" element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="setup" element={<Setup />} />
        <Route path="traces" element={<Traces />} />
        <Route path="review" element={<Review />} />
        <Route path="group" element={<Later title="Group failures" />} />
        <Route path="count" element={<Later title="Count and prioritise" />} />
        <Route path="decide" element={<Later title="Decide what each failure needs" />} />
        <Route path="build" element={<Later title="Build evaluators" />} />
        <Route path="validate" element={<Later title="Validate judges" />} />
        <Route path="run" element={<Later title="Run and measure" />} />
        <Route path="export" element={<Later title="Export and operate" />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
