import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppHeader } from "@/components/layout/AppHeader";
import { JobsFeedPage } from "@/pages/JobsFeedPage";
import { ProfilePage } from "@/pages/ProfilePage";
import { ApplicationsPage } from "@/pages/ApplicationsPage";

function App() {
  return (
    <BrowserRouter>
      <AppHeader />
      <Routes>
        <Route path="/" element={<JobsFeedPage />} />
        <Route path="/applications" element={<ApplicationsPage />} />
        <Route path="/profile" element={<ProfilePage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
