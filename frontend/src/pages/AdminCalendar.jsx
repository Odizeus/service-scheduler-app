import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtTimeBlock, ymd } from "@/lib/dates";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  ToggleGroup, ToggleGroupItem,
} from "@/components/ui/toggle-group";
import { ChevronLeft, ChevronRight, Ban } from "lucide-react";

const STATUS_COLOR = {
  pending: "bg-amber-100 text-amber-800 border-amber-200",
  confirmed: "bg-emerald-100 text-emerald-800 border-emerald-200",
  completed: "bg-blue-100 text-blue-800 border-blue-200",
  cancelled: "bg-rose-100 text-rose-800 border-rose-200",
  no_show: "bg-stone-200 text-stone-700 border-stone-300",
};
const STATUS_DOT = {
  pending: "bg-amber-500",
  confirmed: "bg-emerald-500",
  completed: "bg-blue-500",
  cancelled: "bg-rose-500",
  no_show: "bg-stone-400",
};
const STATUS_LABEL = {
  pending: "Pending", confirmed: "Confirmed", completed: "Completed",
  cancelled: "Cancelled", no_show: "No-show",
};

function startOfWeek(date) {
  // ISO Monday-first
  const d = new Date(date);
  const day = (d.getDay() + 6) % 7; // 0..6 Mon..Sun
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

export default function AdminCalendar() {
  const [view, setView] = useState("month");
  const [anchor, setAnchor] = useState(new Date());

  // Compute date range
  const range = useMemo(() => {
    if (view === "day") return { from: ymd(anchor), to: ymd(anchor) };
    if (view === "week") {
      const start = startOfWeek(anchor);
      return { from: ymd(start), to: ymd(addDays(start, 6)) };
    }
    // month — extend to include the leading/trailing weeks shown in grid
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

  // Group by date
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
          <h2 className="text-2xl font-semibold tracking-tight">Calendar</h2>
          <p className="text-sm text-stone-500">
            <span data-testid="calendar-total-count">{totalAppts}</span> appointment{totalAppts === 1 ? "" : "s"} in view
          </p>
        </div>
        <div className="flex items-center gap-3">
          <ToggleGroup
            type="single"
            value={view}
            onValueChange={(v) => v && setView(v)}
            data-testid="calendar-view-switcher"
          >
            <ToggleGroupItem value="month" data-testid="calendar-view-month">Month</ToggleGroupItem>
            <ToggleGroupItem value="week" data-testid="calendar-view-week">Week</ToggleGroupItem>
            <ToggleGroupItem value="day" data-testid="calendar-view-day">Day</ToggleGroupItem>
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

      <div className="text-sm font-medium text-stone-700" data-testid="calendar-header-label">
        {headerLabel()}
      </div>

      <Legend />

      <Card>
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
              business={bizQ.data}
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
    <div className="flex flex-wrap items-center gap-3 text-xs text-stone-600" data-testid="calendar-legend">
      {Object.entries(STATUS_LABEL).map(([k, label]) => (
        <span key={k} className="inline-flex items-center gap-1.5">
          <span className={`h-2 w-2 rounded-full ${STATUS_DOT[k]}`} />
          {label}
        </span>
      ))}
      <span className="inline-flex items-center gap-1.5 ml-3">
        <Ban className="h-3 w-3 text-stone-500" /> Blocked
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
      <div className="grid grid-cols-7 gap-1 text-xs text-stone-500 mb-2">
        {heads.map((h) => <div key={h} className="text-center font-medium">{h}</div>)}
      </div>
      <div className="grid grid-cols-7 gap-1">
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
                "relative min-h-[88px] rounded-md border p-1.5 text-left transition",
                inMonth ? "bg-white" : "bg-stone-50",
                dayBlocked ? "border-stone-300" : "border-stone-200",
                "hover:border-stone-400",
              ].join(" ")}
            >
              <div className="flex items-center justify-between">
                <span className={["text-xs", inMonth ? "text-stone-800" : "text-stone-400"].join(" ")}>
                  {d.getDate()}
                </span>
                {appts.length > 0 && (
                  <Badge
                    variant="secondary"
                    className="h-5 px-1.5 text-[10px]"
                    data-testid={`calendar-day-count-${ds}`}
                  >
                    {appts.length}
                  </Badge>
                )}
              </div>
              {dayBlocked && (
                <div
                  data-testid={`calendar-blocked-day-${ds}`}
                  className="absolute inset-1.5 rounded bg-stone-100/60 flex items-center justify-center pointer-events-none"
                >
                  <Ban className="h-3 w-3 text-stone-500" />
                </div>
              )}
              <div className="mt-1 space-y-0.5">
                {appts.slice(0, 3).map((a) => (
                  <div
                    key={a.id}
                    className="flex items-center gap-1 text-[10px] text-stone-600 truncate"
                  >
                    <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${STATUS_DOT[a.status] || "bg-stone-400"}`} />
                    <span className="truncate">{a.local_time_block.split("-")[0]} · {a.customer?.full_name || ""}</span>
                  </div>
                ))}
                {appts.length > 3 && (
                  <div className="text-[10px] text-stone-500">+{appts.length - 3} more</div>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function WeekView({ anchor, byDate, blocksByDate, business }) {
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
            className="border rounded-md p-2 bg-white min-h-[180px]"
          >
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs font-medium text-stone-700">
                {d.toLocaleDateString(undefined, { weekday: "short" })} {d.getDate()}
              </div>
              <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">
                {appts.length}
              </Badge>
            </div>
            {blk?.day && (
              <div
                data-testid={`calendar-blocked-day-${ds}`}
                className="mb-2 flex items-center gap-1 text-[11px] text-stone-600 bg-stone-100 rounded px-2 py-1"
              >
                <Ban className="h-3 w-3" /> Day blocked
              </div>
            )}
            <div className="space-y-1">
              {appts.map((a) => (
                <div
                  key={a.id}
                  data-testid={`calendar-appt-${a.id}`}
                  className={`rounded border px-2 py-1 text-[11px] ${STATUS_COLOR[a.status] || "bg-stone-100"}`}
                >
                  <div className="font-medium">{fmtTimeBlock(a.local_time_block)}</div>
                  <div className="truncate">{a.customer?.full_name}</div>
                  <div className="truncate opacity-70">{a.service_type}</div>
                </div>
              ))}
              {blk?.slots && Array.from(blk.slots).map((tb) => (
                <div
                  key={tb}
                  data-testid={`calendar-blocked-slot-${ds}-${tb}`}
                  className="rounded border border-dashed border-stone-300 px-2 py-1 text-[11px] text-stone-500 flex items-center gap-1"
                >
                  <Ban className="h-3 w-3" /> {fmtTimeBlock(tb)}
                </div>
              ))}
              {appts.length === 0 && !blk && (
                <div className="text-[11px] text-stone-400">—</div>
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
  // Generate slot template for the day
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
      <div data-testid="calendar-day-view" className="text-center py-8">
        <Ban className="h-8 w-8 text-stone-400 mx-auto mb-2" />
        <p className="text-sm text-stone-600">This day is blocked.</p>
        <p className="text-xs text-stone-400">{date}</p>
      </div>
    );
  }

  return (
    <div data-testid="calendar-day-view" className="space-y-2">
      {slots.length === 0 && (
        <p className="text-sm text-stone-500">No business hours configured.</p>
      )}
      {slots.map((tb) => {
        const a = byTb[tb];
        const slotBlocked = block?.slots?.has(tb);
        if (a) {
          return (
            <div
              key={tb}
              data-testid={`calendar-appt-${a.id}`}
              className={`flex items-start gap-3 rounded-md border p-3 ${STATUS_COLOR[a.status] || "bg-white"}`}
            >
              <div className="w-28 text-sm font-mono shrink-0">{fmtTimeBlock(tb)}</div>
              <div className="flex-1">
                <div className="font-medium text-sm">{a.customer?.full_name}</div>
                <div className="text-xs opacity-80">
                  {a.service_type} · {a.customer?.phone}
                </div>
                {a.description && (
                  <div className="text-xs opacity-70 mt-1 line-clamp-2">{a.description}</div>
                )}
              </div>
              <Badge variant="outline" className="text-[10px]">
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
              className="flex items-center gap-3 rounded-md border border-dashed border-stone-300 p-3 text-stone-500"
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
            className="flex items-center gap-3 rounded-md border border-stone-200 p-3 text-stone-400"
          >
            <div className="w-28 text-sm font-mono shrink-0">{fmtTimeBlock(tb)}</div>
            <span className="text-sm">Available</span>
          </div>
        );
      })}
    </div>
  );
}
