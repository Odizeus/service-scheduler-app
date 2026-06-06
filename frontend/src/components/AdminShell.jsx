import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, getToken, logoutAdmin, DEFAULT_SLUG } from "@/lib/api";
import { ADMIN } from "@/constants/testIds";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { useEffect, useState } from "react";
import {
  CalendarRange,
  Settings,
  LayoutList,
  Mail,
  LogOut,
  Users,
  CalendarDays,
  Menu,
} from "lucide-react";

const NAV_ITEMS = [
  {
    to: "/admin/appointments",
    label: "Appointments",
    icon: LayoutList,
    testId: ADMIN.navAppointments,
  },
  {
    to: "/admin/calendar",
    label: "Calendar",
    icon: CalendarDays,
    testId: "admin-nav-calendar",
  },
  {
    to: "/admin/availability",
    label: "Availability",
    icon: CalendarRange,
    testId: ADMIN.navAvailability,
  },
  {
    to: "/admin/business",
    label: "Business",
    icon: Settings,
    testId: ADMIN.navBusiness,
  },
  {
    to: "/admin/templates",
    label: "Email templates",
    icon: Mail,
    testId: ADMIN.navTemplates,
  },
  {
    to: "/admin/users",
    label: "Admin users",
    icon: Users,
    testId: "admin-nav-users",
  },
];

export default function AdminShell() {
  const navigate = useNavigate();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    if (!getToken()) navigate("/admin/login", { replace: true });
  }, [navigate]);

  const meQ = useQuery({
    queryKey: ["me"],
    queryFn: async () => (await api.get("/admin/me")).data,
    enabled: !!getToken(),
  });

  const logout = async () => {
    await logoutAdmin();
    navigate(`/book/${meQ.data?.business?.slug || DEFAULT_SLUG}`, { replace: true });
  };

  const linkCls = ({ isActive }) =>
    [
      "group flex items-center gap-2 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 border",
      isActive
        ? "bg-[#d4af37] text-zinc-950 border-[#d4af37] shadow-[0_10px_30px_rgba(212,175,55,0.22)]"
        : "text-zinc-300 border-transparent hover:bg-zinc-800/80 hover:text-white hover:border-zinc-700",
    ].join(" ");

  const NavLinks = ({ onNavigate }) => (
    <nav className="space-y-1.5">
      {NAV_ITEMS.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink
            key={item.to}
            data-testid={item.testId}
            to={item.to}
            className={linkCls}
            onClick={onNavigate}
          >
            <Icon className="h-4 w-4" /> {item.label}
          </NavLink>
        );
      })}
    </nav>
  );

  return (
    <div className="min-h-screen bg-transparent">
      <header className="sticky top-0 z-40 border-b border-zinc-800/80 bg-zinc-950/85 backdrop-blur-xl">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-4 flex items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <Sheet open={mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
              <SheetTrigger asChild>
                <Button
                  variant="outline"
                  size="icon"
                  className="md:hidden shrink-0 border-zinc-700 bg-zinc-900 text-zinc-100 hover:border-[#d4af37]"
                  aria-label="Open admin menu"
                >
                  <Menu className="h-5 w-5" />
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="w-[280px] border-zinc-800 bg-zinc-950 text-zinc-100">
                <SheetHeader>
                  <SheetTitle className="text-zinc-100">{meQ.data?.business?.name || "Admin"}</SheetTitle>
                </SheetHeader>
                <div className="mt-6">
                  <NavLinks onNavigate={() => setMobileMenuOpen(false)} />
                </div>
              </SheetContent>
            </Sheet>

            <div className="min-w-0">
              <Link
                to="/admin/appointments"
                className="block truncate text-lg font-semibold tracking-tight text-zinc-50 hover:text-[#f5d76e]"
              >
                {meQ.data?.business?.name || "Admin"}
              </Link>
              <div className="text-xs text-zinc-500">Scheduler · Admin Console</div>
            </div>
          </div>

          <div className="flex items-center gap-2 sm:gap-3 text-sm">
            <span className="hidden sm:inline text-zinc-500 truncate max-w-[220px]">
              {meQ.data?.user?.email}
            </span>
            <Button
              data-testid={ADMIN.logout}
              variant="outline"
              size="sm"
              onClick={logout}
              className="touch-manipulation border-zinc-700 bg-zinc-900 text-zinc-100 hover:border-[#d4af37] hover:bg-zinc-800"
            >
              <LogOut className="h-4 w-4 sm:mr-1" />
              <span className="hidden sm:inline">Logout</span>
            </Button>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-6 md:py-8 grid gap-6 md:gap-8 md:grid-cols-[220px_1fr]">
        <aside className="hidden md:block rounded-2xl border border-zinc-800/80 bg-zinc-950/45 p-3 h-fit shadow-[0_20px_50px_rgba(0,0,0,0.22)]">
          <div className="px-3 pb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500">
            Navigation
          </div>
          <NavLinks />
        </aside>
        <main className="min-w-0">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
