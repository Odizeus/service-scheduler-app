import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtTimeBlock, ymd } from "@/lib/dates";
import { customerColorStyle, customerDotStyle } from "@/lib/customerColor";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  ToggleGroup, ToggleGroupItem,
} from "@/components/ui/toggle-group";
import { ChevronLeft, ChevronRight, Ban } from "lucide-react";

const STATUS_COLOR = {
  pending: "bg-amber-500/15 text-amber-200 border-amber-400/40",
  confirmed: "bg-emerald-500/15 text-emerald-200 border-emerald-400/40",
  completed: "bg-blue-500/15 text-blue-200 border-blue-400/40",
  cancelled: "bg-rose-500/15 text-rose-200 border-rose-400/40",
  no_show: "bg-zinc-700/70 text-zinc-200 border-zinc-600",
};
const STATUS_DOT = {
  pending: "bg-amber-400",
  confirmed: "bg-emerald-400",
  completed: "bg-blue-400",
  cancelled: "bg-rose-400",
  no_show: "bg-zinc-400",
};
const STATUS_LABEL = {
  pending: "Pending", confirmed: "Confirmed", completed: "Completed",
  cancelled: "Cancelled", no_show: "No-show",
};

function startOfWeek(date) {
  const d = new Date(date);
  const day = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - day);
  d.setHours(0, 0, 0, 0);
  return d;
}
function addDays(d, n) {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}
function monthRange(anchor) {
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  const last = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0);
  return { from: ymd(first), to: ymd(last), first, last };
}

function CustomerColorDot({ customer, className = "h-1.5 w-1.5" }) {
  return <span className={`${className} rounded-full shrink-0`} style={customerDotStyle(customer)} />;
}

function customerAccentStyle(customer) {
  const color = customerColorStyle(customer);
  return {
    ...color,
    boxShadow: `inset 3px 0 0 ${color["--customer-color"]}, 0 10px 24px rgba(0,0,0,0.16)`,
  };
}

export default function AdminCalendar() {
  const [view, setView] = useState("month");
  const [anchor, setAnchor] = useState(new Date());

  const range = useMemo(() => {
    if (view === "day") return { from: ymd(anchor), to: ymd(anchor) };
    if (view === "week") {
      const start = startOfWeek(anchor);
      return { from: ymd(start), to: ymd(addDays(start, 6)) };
    }
    const m = monthRange(anchor);
    const gridStart = startOfWeek(m.first);
    const gridEnd = addDays(startOfWeek(m.last), 6);
    return { from: ymd(gridStart), to: ymd(gridEnd) };
  }, [view, anchor]);

  const bizQ = useQuery({
    queryKey: ["business"],
    queryFn: async () => (await api.get("/admin/business")).data,
  });

  const apptQ = useQuery({
    queryKey: ["calendar-appts", range],
    queryFn: async () => (await api.get("/admin/appointments", { params: range })).data,
  });

  const ovQ = useQuery({
    queryKey: ["calendar-overrides", range],
    queryFn: async () =>
      (await api.get("/admin/availability-overrides", { params: range })).data,
  });

  const byDate = useMemo(() => {
    const m = {};
    (apptQ.data?.items || []).forEach((a) => {
      (m[a.local_date] = m[a.local_date] || []).push(a);
    });
    Object.values(m).forEach((arr) =>
      arr.sort((x, y) => x.local_time_block.localeCompare(y.local_time_block))
    );
    return m;
  }, [apptQ.data]);

  const blocksByDate = useMemo(() => {
    const out = {};
    (ovQ.data?.items || []).forEach((o) => {
      if (o.action !== "block") return;
      out[o.local_date] = out[o.local_date] || { day: false, slots: new Set() };
      if (o.scope === "day") out[o.local_date].day = true;
      else if (o.local_time_block) out[o.local_date].slots.add(o.local_time_block);
    });
    return out;
  }, [ovQ.data]);

  const totalAppts = (apptQ.data?.items || []).length;

  const shift = (dir) => {
    if (view === "day") setAnchor(addDays(anchor, dir));
    else if (view === "week") setAnchor(addDays(anchor, dir * 7));
    else {
      const next = new Date(anchor);
      next.setMonth(next.getMonth() + dir);
      setAnchor(next);
    }
  };

  const headerLabel = () => {
    if (view === "day") {
      return anchor.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
    }
    if (view === "week") {
      const s = startOfWeek(anchor);
      const e = addDays(s, 6);
      return `${s.toLocaleDateString(undefined, { month: "short", day: "numeric" })} – ${e.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`;
    }
    return anchor.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  };

  return (
    <div className="space-y-6" data-testid="calendar-dashboard">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-zinc-50">Calendar</h2>
          <p className="text-sm text-zinc-400">
            <span data-testid="calendar-total-count">{totalAppts}</span> appointment{totalAppts === 1 ? "" : "s"} in view
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <ToggleGroup
            type="single"
            value={view}
            onValueChange={(v) => v && setView(v)}
            data-testid="calendar-view-switcher"
            className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-1"
          >
            <ToggleGroupItem value="month" data-testid="calendar-view-month" className="data-[state=on]:bg-[#d4af37] data-[state=on]:text-zinc-950 text-zinc-300 rounded-lg">Month</ToggleGroupItem>
            <ToggleGroupItem value="week" data-testid="calendar-view-week" className="data-[state=on]:bg-[#d4af37] data-[state=on]:text-zinc-950 text-zinc-300 rounded-lg">Week</ToggleGroupItem>
            <ToggleGroupItem value="day" data-testid="calendar-view-day" className="data-[state=on]:bg-[#d4af37] data-[state=on]:text-zinc-950 text-zinc-300 rounded-lg">Day</ToggleGroupItem>
          </ToggleGroup>
          <div className="flex items-center gap-1">
            <Button data-testid="calendar-prev" variant="outline" size="icon" onClick={() => shift(-1)}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button data-testid="calendar-today" variant="outline" size="sm" onClick={() => setAnchor(new Date())}>
              Today
            </Button>
            <Button data-testid="calendar-next" variant="outline" size="icon" onClick={() => shift(1)}>
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-zinc-800 bg-zinc-950/45 px-4 py-3 text-sm font-medium text-[#f5d76e]" data-testid="calendar-header-label">
        {headerLabel()}
      </div>

      <Legend />

      <Card className="border-zinc-800 bg-zinc-950/55 shadow-[0_22px_60px_rgba(0,0,0,0.3)]">
        <CardContent className="p-4">
          {view === "month" && (
            <MonthView
              anchor={anchor}
              byDate={byDate}
              blocksByDate={blocksByDate}
              onPick={(d) => { setAnchor(d); setView("day"); }}
            />
          )}
          {view === "week" && (
            <WeekView
              anchor={anchor}
              byDate={byDate}
              blocksByDate={blocksByDate}
            />
          )}
          {view === "day" && (
            <DayView
              date={ymd(anchor)}
              appts={byDate[ymd(anchor)] || []}
              block={blocksByDate[ymd(anchor)]}
              business={bizQ.data}
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-zinc-800 bg-zinc-950/35 px-4 py-3 text-xs text-zinc-300" data-testid="calendar-legend">
      {Object.entries(STATUS_LABEL).map(([k, label]) => (
        <span key={k} className="inline-flex items-center gap-1.5">
          <span className={`h-2 w-2 rounded-full shadow-[0_0_10px_currentColor] ${STATUS_DOT[k]}`} />
          {label}
        </span>
      ))}
      <span className="inline-flex items-center gap-1.5 sm:ml-3 text-zinc-400">
        <Ban className="h-3 w-3" /> Blocked
      </span>
      <span className="inline-flex items-center gap-1.5 sm:ml-3 text-zinc-400">
        <span className="h-2 w-2 rounded-full bg-[#d4af37]" /> Customer colors
      </span>
    </div>
  );
}

function MonthView({ anchor, byDate, blocksByDate, onPick }) {
  const m = monthRange(anchor);
  const gridStart = startOfWeek(m.first);
  const cells = Array.from({ length: 42 }, (_, i) => addDays(gridStart, i));
  const heads = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  return (
    <div data-testid="calendar-month-view">
      <div className="grid grid-cols-7 gap-1 text-xs text-zinc-500 mb-2">
        {heads.map((h) => <div key={h} className="text-center font-semibold uppercase tracking-wide">{h}</div>)}
      </div>
      <div className="grid grid-cols-7 gap-1.5">
        {cells.map((d) => {
          const ds = ymd(d);
          const inMonth = d.getMonth() === anchor.getMonth();
          const appts = byDate[ds] || [];
          const blk = blocksByDate[ds];
          const dayBlocked = blk?.day;
          return (
            <button
              key={ds}
              data-testid={`calendar-month-day-${ds}`}
              onClick={() => onPick(d)}
              className={[
                "group relative min-h-[92px] rounded-xl border p-2 text-left transition-all duration-200",
                inMonth ? "bg-zinc-900/90 border-zinc-800" : "bg-zinc-950/65 border-zinc-900 opacity-75",
                dayBlocked ? "border-zinc-600" : "",
                "hover:border-[#d4af37] hover:bg-zinc-800/80 hover:shadow-[0_12px_35px_rgba(0,0,0,0.28)]",
              ].join(" ")}
            >
              <div className="flex items-center justify-between">
                <span className={["text-xs font-semibold", inMonth ? "text-zinc-100" : "text-zinc-600"].join(" ")}>
                  {d.getDate()}
                </span>
                {appts.length > 0 && (
                  <Badge
                    variant="secondary"
                    className="h-5 px-1.5 text-[10px] border border-[#d4af37]/30 bg-[#d4af37]/15 text-[#f5d76e]"
                    data-testid={`calendar-day-count-${ds}`}
                  >
                    {appts.length}
                  </Badge>
                )}
              </div>
              {dayBlocked && (
                <div
                  data-testid={`calendar-blocked-day-${ds}`}
                  className="absolute inset-1.5 rounded-lg border border-dashed border-zinc-600 bg-zinc-950/75 flex items-center justify-center pointer-events-none"
                >
                  <Ban className="h-4 w-4 text-zinc-400" />
                </div>
              )}
              <div className="mt-2 space-y-1">
                {appts.slice(0, 3).map((a) => (
                  <div
                    key={a.id}
                    className="flex items-center gap-1.5 rounded-md px-1.5 py-1 text-[10px] truncate border"
                    style={customerColorStyle(a.customer)}
                    title={`${a.customer?.full_name || "Customer"} · ${fmtTimeBlock(a.local_time_block)}`}
                  >
                    <CustomerColorDot customer={a.customer} />
                    <span className="truncate">{a.local_time_block.split("-")[0]} · {a.customer?.full_name || "Customer"}</span>
                  </div>
                ))}
                {appts.length > 3 && (
                  <div className="text-[10px] text-[#f5d76e]">+{appts.length - 3} more</div>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function WeekView({ anchor, byDate, blocksByDate }) {
  const start = startOfWeek(anchor);
  const days = Array.from({ length: 7 }, (_, i) => addDays(start, i));
  return (
    <div data-testid="calendar-week-view" className="grid grid-cols-1 md:grid-cols-7 gap-3">
      {days.map((d) => {
        const ds = ymd(d);
        const appts = byDate[ds] || [];
        const blk = blocksByDate[ds];
        return (
          <div
            key={ds}
            data-testid={`calendar-week-day-${ds}`}
            className="rounded-xl border border-zinc-800 bg-zinc-900/75 p-3 min-h-[190px]"
          >
            <div className="flex items-center justify-between mb-3">
              <div className="text-xs font-semibold text-zinc-100">
                {d.toLocaleDateString(undefined, { weekday: "short" })} {d.getDate()}
              </div>
              <Badge variant="secondary" className="h-5 px-1.5 text-[10px] border border-zinc-700 bg-zinc-950 text-zinc-300">
                {appts.length}
              </Badge>
            </div>
            {blk?.day && (
              <div
                data-testid={`calendar-blocked-day-${ds}`}
                className="mb-2 flex items-center gap-1 text-[11px] text-zinc-300 bg-zinc-950/75 border border-dashed border-zinc-600 rounded-lg px-2 py-1"
              >
                <Ban className="h-3 w-3" /> Day blocked
              </div>
            )}
            <div className="space-y-1.5">
              {appts.map((a) => (
                <div
                  key={a.id}
                  data-testid={`calendar-appt-${a.id}`}
                  className={`rounded-lg border px-2 py-1.5 text-[11px] ${STATUS_COLOR[a.status] || ""}`}
                  style={customerAccentStyle(a.customer)}
                >
                  <div className="font-semibold flex items-center gap-1.5">
                    <CustomerColorDot customer={a.customer} /> {fmtTimeBlock(a.local_time_block)}
                  </div>
                  <div className="truncate">{a.customer?.full_name}</div>
                  <div className="truncate opacity-75">{a.service_type}</div>
                </div>
              ))}
              {blk?.slots && Array.from(blk.slots).map((tb) => (
                <div
                  key={tb}
                  data-testid={`calendar-blocked-slot-${ds}-${tb}`}
                  className="rounded-lg border border-dashed border-zinc-600 bg-zinc-950/60 px-2 py-1.5 text-[11px] text-zinc-400 flex items-center gap-1"
                >
                  <Ban className="h-3 w-3" /> {fmtTimeBlock(tb)}
                </div>
              ))}
              {appts.length === 0 && !blk && (
                <div className="rounded-lg border border-dashed border-zinc-800 px-2 py-3 text-center text-[11px] text-zinc-600">No appointments</div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function DayView({ date, appts, block, business }) {
  const av = business?.availability;
  const slots = useMemo(() => {
    if (!av) return [];
    const out = [];
    const [sh, sm] = av.day_start.split(":").map(Number);
    const [eh, em] = av.day_end.split(":").map(Number);
    const step = av.block_minutes + (av.buffer_minutes || 0);
    let cur = sh * 60 + sm;
    const end = eh * 60 + em;
    const block_m = av.block_minutes;
    while (cur + block_m <= end) {
      const s = `${String(Math.floor(cur / 60)).padStart(2, "0")}:${String(cur % 60).padStart(2, "0")}`;
      const e = `${String(Math.floor((cur + block_m) / 60)).padStart(2, "0")}:${String((cur + block_m) % 60).padStart(2, "0")}`;
      out.push(`${s}-${e}`);
      cur += step;
    }
    return out;
  }, [av]);

  const byTb = useMemo(() => {
    const m = {};
    appts.forEach((a) => (m[a.local_time_block] = a));
    return m;
  }, [appts]);

  if (block?.day) {
    return (
      <div data-testid="calendar-day-view" className="text-center py-10 rounded-2xl border border-dashed border-zinc-700 bg-zinc-950/60">
        <Ban className="h-8 w-8 text-zinc-400 mx-auto mb-2" />
        <p className="text-sm text-zinc-300">This day is blocked.</p>
        <p className="text-xs text-zinc-500">{date}</p>
      </div>
    );
  }

  return (
    <div data-testid="calendar-day-view" className="space-y-2">
      {slots.length === 0 && (
        <p className="text-sm text-zinc-400">No business hours configured.</p>
      )}
      {slots.map((tb) => {
        const a = byTb[tb];
        const slotBlocked = block?.slots?.has(tb);
        if (a) {
          return (
            <div
              key={tb}
              data-testid={`calendar-appt-${a.id}`}
              className={`flex items-start gap-3 rounded-xl border p-3 ${STATUS_COLOR[a.status] || ""}`}
              style={customerAccentStyle(a.customer)}
            >
              <div className="w-28 text-sm font-mono shrink-0 flex items-center gap-2">
                <CustomerColorDot customer={a.customer} className="h-2.5 w-2.5" />
                {fmtTimeBlock(tb)}
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-sm truncate">{a.customer?.full_name}</div>
                <div className="text-xs opacity-80 truncate">
                  {a.service_type} · {a.customer?.phone}
                </div>
                {a.description && (
                  <div className="text-xs opacity-70 mt-1 line-clamp-2">{a.description}</div>
                )}
              </div>
              <Badge variant="outline" className="text-[10px] border-current shrink-0">
                {STATUS_LABEL[a.status] || a.status}
              </Badge>
            </div>
          );
        }
        if (slotBlocked) {
          return (
            <div
              key={tb}
              data-testid={`calendar-blocked-slot-${date}-${tb}`}
              className="flex items-center gap-3 rounded-xl border border-dashed border-zinc-600 bg-zinc-950/60 p-3 text-zinc-400"
            >
              <div className="w-28 text-sm font-mono shrink-0">{fmtTimeBlock(tb)}</div>
              <Ban className="h-4 w-4" />
              <span className="text-sm">Blocked</span>
            </div>
          );
        }
        return (
          <div
            key={tb}
            className="flex items-center gap-3 rounded-xl border border-zinc-800 bg-zinc-900/45 p-3 text-zinc-500"
          >
            <div className="w-28 text-sm font-mono shrink-0">{fmtTimeBlock(tb)}</div>
            <span className="text-sm">Available</span>
          </div>
        );
      })}
    </div>
  );
}
