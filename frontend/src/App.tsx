import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Build } from "./pages/Build";
import { Count } from "./pages/Count";
import { Decide } from "./pages/Decide";
import { Group } from "./pages/Group";
import { Home } from "./pages/Home";
import { Later } from "./pages/Later";
import { Projects } from "./pages/Projects";
import { Review } from "./pages/Review";
import { Settings } from "./pages/Settings";
import { Setup } from "./pages/Setup";
import { Traces } from "./pages/Traces";
import { Validate } from "./pages/Validate";

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Projects />} />
      <Route path="/p/:pid" element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="setup" element={<Setup />} />
        <Route path="traces" element={<Traces />} />
        <Route path="review" element={<Review />} />
        <Route path="group" element={<Group />} />
        <Route path="count" element={<Count />} />
        <Route path="decide" element={<Decide />} />
        <Route path="build" element={<Build />} />
        <Route path="validate" element={<Validate />} />
        <Route path="run" element={<Later title="Run and measure" />} />
        <Route path="export" element={<Later title="Export and operate" />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
