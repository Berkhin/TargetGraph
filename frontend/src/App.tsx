import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppHeader } from "@/components/layout/AppHeader";
import { JobsFeedPage } from "@/pages/JobsFeedPage";
import { ProfilePage } from "@/pages/ProfilePage";
import { CoverLettersPage } from "@/features/cover-letters/ui/CoverLettersPage";

function App() {
  return (
    <BrowserRouter>
      <AppHeader />
      <Routes>
        <Route path="/" element={<JobsFeedPage />} />
        <Route path="/cover-letters" element={<CoverLettersPage />} />
        <Route path="/profile" element={<ProfilePage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
