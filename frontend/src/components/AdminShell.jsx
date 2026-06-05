import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, getToken, logoutAdmin } from "@/lib/api";
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
    navigate("/admin/login", { replace: true });
  };

  const linkCls = ({ isActive }) =>
    [
      "flex items-center gap-2 px-3 py-2 rounded-md text-sm transition",
      isActive
        ? "bg-stone-900 text-white"
        : "text-stone-700 hover:bg-stone-100",
    ].join(" ");

  const NavLinks = ({ onNavigate }) => (
    <nav className="space-y-1">
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
    <div className="min-h-screen bg-stone-50">
      <header className="sticky top-0 z-40 bg-white border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-4 flex items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <Sheet open={mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
              <SheetTrigger asChild>
                <Button
                  variant="outline"
                  size="icon"
                  className="md:hidden shrink-0"
                  aria-label="Open admin menu"
                >
                  <Menu className="h-5 w-5" />
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="w-[280px]">
                <SheetHeader>
                  <SheetTitle>{meQ.data?.business?.name || "Admin"}</SheetTitle>
                </SheetHeader>
                <div className="mt-6">
                  <NavLinks onNavigate={() => setMobileMenuOpen(false)} />
                </div>
              </SheetContent>
            </Sheet>

            <div className="min-w-0">
              <Link
                to="/admin/appointments"
                className="block truncate text-lg font-semibold tracking-tight"
              >
                {meQ.data?.business?.name || "Admin"}
              </Link>
              <div className="text-xs text-stone-500">Scheduler · Admin</div>
            </div>
          </div>

          <div className="flex items-center gap-2 sm:gap-3 text-sm">
            <span className="hidden sm:inline text-stone-500 truncate max-w-[220px]">
              {meQ.data?.user?.email}
            </span>
            <Button
              data-testid={ADMIN.logout}
              variant="outline"
              size="sm"
              onClick={logout}
              className="touch-manipulation"
            >
              <LogOut className="h-4 w-4 sm:mr-1" />
              <span className="hidden sm:inline">Logout</span>
            </Button>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-6 md:py-8 grid gap-6 md:gap-8 md:grid-cols-[220px_1fr]">
        <aside className="hidden md:block">
          <NavLinks />
        </aside>
        <main className="min-w-0">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
