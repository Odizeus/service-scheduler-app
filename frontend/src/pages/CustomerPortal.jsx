import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { allowedMonths, fmtTimeBlock, isoWeekday, monthLabel, ymd } from "@/lib/dates";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  CalendarDays, Clock, ChevronLeft, ChevronRight, Phone, Mail, Globe, AlertTriangle, CheckCircle2,
} from "lucide-react";

const STATUS_LABEL = {
  pending: "Pending",
  confirmed: "Confirmed",
  cancelled: "Cancelled",
  completed: "Completed",
  no_show: "No-show",
};

export default function CustomerPortal() {
  const { token } = useParams();
  const qc = useQueryClient();
  const [view, setView] = useState("details"); // details | reschedule
  const [monthIdx, setMonthIdx] = useState(0);
  const months = useMemo(() => allowedMonths(new Date()), []);
  const cur = months[monthIdx];
  const monthStr = `${cur.y}-${String(cur.m).padStart(2, "0")}`;
  const [selectedDate, setSelectedDate] = useState(null);
  const [selectedSlot, setSelectedSlot] = useState(null);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState("");

  const apptQ = useQuery({
    queryKey: ["portal", token],
    queryFn: async () => (await api.get(`/portal/${token}`)).data,
    retry: false,
  });

  const availQ = useQuery({
    enabled: view === "reschedule" && !!apptQ.data,
    queryKey: ["portal-avail", token, monthStr],
    queryFn: async () =>
      (await api.get(`/portal/${token}/availability`, { params: { month: monthStr } })).data,
  });

  const dayMap = useMemo(() => {
    const m = {};
    availQ.data?.days?.forEach((d) => (m[d.date] = d));
    return m;
  }, [availQ.data]);

  const reschedule = useMutation({
    mutationFn: async () =>
      (await api.post(`/portal/${token}/reschedule`, {
        local_date: selectedDate,
        local_time_block: selectedSlot,
      })).data,
    onSuccess: () => {
      toast.success("Appointment rescheduled");
      qc.invalidateQueries({ queryKey: ["portal", token] });
      qc.invalidateQueries({ queryKey: ["portal-avail", token] });
      setView("details");
      setSelectedDate(null);
      setSelectedSlot(null);
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Reschedule failed"),
  });

  const cancel = useMutation({
    mutationFn: async () =>
      (await api.post(`/portal/${token}/cancel`, { reason: cancelReason })).data,
    onSuccess: () => {
      toast.success("Appointment cancelled");
      qc.invalidateQueries({ queryKey: ["portal", token] });
      setCancelOpen(false);
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Cancel failed"),
  });

  // -------- Token errors --------
  if (apptQ.isError) {
    const status = apptQ.error?.response?.status;
    const detail = apptQ.error?.response?.data?.detail;
    const isExpired = status === 410;
    return (
      <ErrorScreen
        kind={isExpired ? "expired" : "invalid"}
        message={
          detail ||
          (isExpired
            ? "This link has expired."
            : "We couldn't find an appointment for this link.")
        }
      />
    );
  }
  if (!apptQ.data) {
    return <div className="min-h-screen bg-stone-50 flex items-center justify-center text-stone-500">Loading...</div>;
  }

  const appt = apptQ.data;
  const biz = appt.business;
  const isCancelled = appt.status === "cancelled";
  const canModify = !isCancelled;

  return (
    <div className="min-h-screen bg-stone-50" data-testid="portal-page">
      <header className="border-b bg-white">
        <div className="max-w-3xl mx-auto px-6 py-6 flex items-center justify-between flex-wrap gap-3">
          <div>
            <div className="text-xs uppercase tracking-wider text-stone-500">Your appointment</div>
            <h1 className="text-2xl font-semibold tracking-tight text-stone-900" data-testid="portal-business-name">
              {biz.name}
            </h1>
          </div>
          <Badge data-testid="portal-status-badge" variant={isCancelled ? "destructive" : "default"}>
            {STATUS_LABEL[appt.status] || appt.status}
          </Badge>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8 space-y-6">
        {view === "details" && (
          <Card className="bg-white" data-testid="portal-details-card">
            <CardHeader>
              <CardTitle className="text-lg">Appointment details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <Row label="Confirmation code" value={appt.confirmation_code} mono />
              <Row label="Service" value={appt.service_type} />
              <Row label="Date" value={appt.local_date} />
              <Row label="Time" value={fmtTimeBlock(appt.local_time_block)} />
              <Row label="Name" value={appt.customer.full_name} />
              <Row label="Email" value={appt.customer.email} />
              <Row label="Phone" value={appt.customer.phone} />
              <Row label="Address" value={appt.customer.address} />
              {appt.description && <Row label="Notes" value={appt.description} />}
              <div className="border-t border-stone-200 my-2" />
              {biz.contact_phone && (
                <Row label="Contact" value={biz.contact_phone} icon={<Phone className="h-4 w-4" />} />
              )}
              {biz.contact_email && (
                <Row label="Email" value={biz.contact_email} icon={<Mail className="h-4 w-4" />} />
              )}
              {biz.website && (
                <Row label="Website" value={biz.website} icon={<Globe className="h-4 w-4" />} />
              )}

              {canModify ? (
                <div className="pt-3 flex flex-col sm:flex-row gap-2">
                  <Button
                    data-testid="portal-reschedule-btn"
                    className="flex-1"
                    onClick={() => setView("reschedule")}
                  >
                    Reschedule
                  </Button>
                  <Button
                    data-testid="portal-cancel-btn"
                    variant="destructive"
                    className="flex-1"
                    onClick={() => setCancelOpen(true)}
                  >
                    Cancel appointment
                  </Button>
                </div>
              ) : (
                <div className="pt-3 flex items-center gap-2 text-stone-600 text-sm">
                  <CheckCircle2 className="h-4 w-4 text-rose-600" />
                  This appointment has been cancelled.
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {view === "reschedule" && (
          <Card className="bg-white" data-testid="portal-reschedule-card">
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="text-lg flex items-center gap-2">
                  <CalendarDays className="h-5 w-5" /> Pick a new date &amp; time
                </CardTitle>
                <div className="flex items-center gap-2">
                  <Button
                    data-testid="portal-month-prev"
                    variant="outline"
                    size="icon"
                    disabled={monthIdx === 0}
                    onClick={() => { setMonthIdx(0); setSelectedDate(null); setSelectedSlot(null); }}
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                  <div className="text-sm font-medium w-36 text-center">
                    {monthLabel(cur.y, cur.m)}
                  </div>
                  <Button
                    data-testid="portal-month-next"
                    variant="outline"
                    size="icon"
                    disabled={monthIdx === 1}
                    onClick={() => { setMonthIdx(1); setSelectedDate(null); setSelectedSlot(null); }}
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <CalendarGrid
                year={cur.y}
                month={cur.m}
                dayMap={dayMap}
                selectedDate={selectedDate}
                onSelect={(d) => { setSelectedDate(d); setSelectedSlot(null); }}
              />
              {selectedDate && (
                <div className="mt-6">
                  <div className="text-sm font-medium text-stone-700 mb-3 flex items-center gap-2">
                    <Clock className="h-4 w-4" /> Time blocks on {selectedDate}
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                    {dayMap[selectedDate]?.slots?.length ? (
                      dayMap[selectedDate].slots.map((s) => (
                        <Button
                          key={s.time_block}
                          data-testid={`portal-slot-${s.time_block}`}
                          variant={selectedSlot === s.time_block ? "default" : "outline"}
                          disabled={!s.available}
                          onClick={() => setSelectedSlot(s.time_block)}
                        >
                          {fmtTimeBlock(s.time_block)}
                        </Button>
                      ))
                    ) : (
                      <p className="text-sm text-stone-500 col-span-3">No slots.</p>
                    )}
                  </div>
                </div>
              )}
              <div className="mt-6 flex flex-col sm:flex-row gap-2">
                <Button
                  variant="outline"
                  className="flex-1"
                  onClick={() => { setView("details"); setSelectedDate(null); setSelectedSlot(null); }}
                >
                  Back
                </Button>
                <Button
                  data-testid="portal-reschedule-confirm"
                  className="flex-1"
                  disabled={!selectedDate || !selectedSlot || reschedule.isPending}
                  onClick={() => reschedule.mutate()}
                >
                  {reschedule.isPending ? "Saving..." : "Confirm new time"}
                </Button>
              </div>
            </CardContent>
          </Card>
        )}
      </main>

      <Dialog open={cancelOpen} onOpenChange={setCancelOpen}>
        <DialogContent data-testid="portal-cancel-dialog">
          <DialogHeader>
            <DialogTitle>Cancel this appointment?</DialogTitle>
            <DialogDescription>
              {appt.local_date} · {fmtTimeBlock(appt.local_time_block)} · {appt.service_type}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label className="text-xs">Reason (optional)</Label>
            <Textarea
              data-testid="portal-cancel-reason"
              rows={3}
              value={cancelReason}
              onChange={(e) => setCancelReason(e.target.value)}
              placeholder="Tell us why so we can improve..."
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCancelOpen(false)}>Keep it</Button>
            <Button
              data-testid="portal-cancel-confirm"
              variant="destructive"
              disabled={cancel.isPending}
              onClick={() => cancel.mutate()}
            >
              {cancel.isPending ? "Cancelling..." : "Cancel appointment"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Row({ label, value, mono, icon }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <span className="text-stone-500 flex items-center gap-2">{icon}{label}</span>
      <span className={"text-stone-900 text-right " + (mono ? "font-mono" : "")}>{value}</span>
    </div>
  );
}

function CalendarGrid({ year, month, dayMap, selectedDate, onSelect }) {
  const first = new Date(year, month - 1, 1);
  const last = new Date(year, month, 0);
  const lead = isoWeekday(first) - 1;
  const totalDays = last.getDate();
  const cells = [];
  for (let i = 0; i < lead; i++) cells.push(null);
  for (let d = 1; d <= totalDays; d++) cells.push(new Date(year, month - 1, d));
  const heads = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  return (
    <div data-testid="portal-calendar">
      <div className="grid grid-cols-7 gap-1 text-xs text-stone-500 mb-2">
        {heads.map((h) => <div key={h} className="text-center">{h}</div>)}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {cells.map((c, i) => {
          if (!c) return <div key={i} />;
          const ds = ymd(c);
          const info = dayMap[ds];
          const isWorking = info?.is_working_day;
          const hasAvail = info?.slots?.some((s) => s.available);
          const disabled = !info || !isWorking || !hasAvail;
          const isSel = selectedDate === ds;
          return (
            <button
              key={ds}
              data-testid={`portal-day-${ds}`}
              disabled={disabled}
              onClick={() => onSelect(ds)}
              className={[
                "h-10 rounded-md border text-sm transition",
                isSel
                  ? "bg-stone-900 text-white border-stone-900"
                  : disabled
                  ? "bg-stone-50 text-stone-300 border-stone-100 cursor-not-allowed"
                  : "bg-white text-stone-800 border-stone-200 hover:border-stone-400",
              ].join(" ")}
            >
              {c.getDate()}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ErrorScreen({ kind, message }) {
  return (
    <div className="min-h-screen bg-stone-50 flex items-center justify-center px-6 py-12" data-testid="portal-error">
      <Card className="w-full max-w-md bg-white">
        <CardHeader>
          <div className="flex items-center gap-3">
            <AlertTriangle className="h-6 w-6 text-amber-600" />
            <CardTitle className="text-lg">
              {kind === "expired" ? "Link expired" : "Link not found"}
            </CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-stone-600" data-testid={`portal-error-${kind}`}>{message}</p>
          <p className="text-xs text-stone-400 mt-4">
            If you need help, please contact the business directly.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
