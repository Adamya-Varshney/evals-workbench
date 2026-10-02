import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Build } from "./pages/Build";
import { Count } from "./pages/Count";
import { Decide } from "./pages/Decide";
import { Export } from "./pages/Export";
import { Glossary } from "./pages/Glossary";
import { Group } from "./pages/Group";
import { Home } from "./pages/Home";
import { Projects } from "./pages/Projects";
import { Review } from "./pages/Review";
import { Run } from "./pages/Run";
import { Settings } from "./pages/Settings";
import { Setup } from "./pages/Setup";
import { Synthetic } from "./pages/Synthetic";
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
        <Route path="run" element={<Run />} />
        <Route path="export" element={<Export />} />
        <Route path="settings" element={<Settings />} />
        <Route path="synthetic" element={<Synthetic />} />
        <Route path="glossary" element={<Glossary />} />
      </Route>
    </Routes>
  );
}
