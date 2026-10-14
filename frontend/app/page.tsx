import { LeadDashboard } from "@/components/lead-dashboard";

// Server shell: the dashboard fetches in the browser (useEffect), so the
// prerendered HTML holds only loading skeletons and no time-dependent text.
export default function Home() {
  return <LeadDashboard />;
}
