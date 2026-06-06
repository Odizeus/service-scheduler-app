import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, API, getToken } from "@/lib/api";
import { ADMIN } from "@/constants/testIds";
import { customerColorStyle, customerDotStyle } from "@/lib/customerColor";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { fmtTimeBlock } from "@/lib/dates";
import { Download, Trash2, X } from "lucide-react";

const STATUS_OPTIONS = ["pending", "confirmed", "completed", "no_show"];
const ELIMINATED_STORAGE_KEY = "service-scheduler-eliminated-cancelled-appointments";
const STATUS_LABEL = {
  pending: "Pending",
  confirmed: "Confirmed",
  cancelled: "Cancelled",
  completed: "Completed",
  no_show: "No-show",
};

const cleanDescription = (description) => {
  if (!description || !description.trim()) return "No details provided.";
  return description.trim();
};

const readEliminatedIds = () => {
  try {
    const raw = window.localStorage.getItem(ELIMINATED_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
};

const saveEliminatedIds = (ids) => {
  window.localStorage.setItem(ELIMINATED_STORAGE_KEY, JSON.stringify(ids));
};

function CustomerColorDot({ customer, className = "h-2.5 w-2.5" }) {
  return <span className={`${className} rounded-full shrink-0`} style={customerDotStyle(customer)} />;
}

function customerCardStyle(customer = {}) {
  const color = customerColorStyle(customer);
  return {
    borderColor: color.border,
    boxShadow: `inset 4px 0 0 ${color["--customer-color"]}, 0 18px 45px rgba(0,0,0,0.22)`,
  };
}

function CustomerPill({ customer }) {
  const color = customerColorStyle(customer);
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-medium"
      style={color}
      title="Customer recognition color"
    >
      <CustomerColorDot customer={customer} className="h-1.5 w-1.5" />
      Customer color
    </span>
  );
}

export default function AdminAppointments() {
  const qc = useQueryClient();
  const [filters, setFilters] = useState({
    status: "all",
    service_type: "all",
    from: "",
    to: "",
    q: "",
  });
  const [eliminatedIds, setEliminatedIds] = useState(() => readEliminatedIds());

  const bizQ = useQuery({
    queryKey: ["business"],
    queryFn: async () => (await api.get("/admin/business")).data,
  });

  const params = {};
  if (filters.status && filters.status !== "all") params.status = filters.status;
  if (filters.service_type && filters.service_type !== "all") params.service_type = filters.service_type;
  if (filters.from) params.from = filters.from;
  if (filters.to) params.to = filters.to;
  if (filters.q) params.q = filters.q;

  const apptQ = useQuery({
    queryKey: ["appointments", params],
    queryFn: async () => (await api.get("/admin/appointments", { params })).data,
  });

  const visibleItems = useMemo(() => {
    const hidden = new Set(eliminatedIds);
    return (apptQ.data?.items || []).filter((a) => !(a.status === "cancelled" && hidden.has(a.id)));
  }, [apptQ.data, eliminatedIds]);

  const cancel = useMutation({
    mutationFn: async ({ id, reason, keep_slot_blocked }) =>
      (await api.post(`/admin/appointments/${id}/cancel`, { reason, keep_slot_blocked })).data,
    onSuccess: () => {
      toast.success("Appointment cancelled");
      qc.invalidateQueries({ queryKey: ["appointments"] });
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Cancel failed"),
  });

  const updateStatus = useMutation({
    mutationFn: async ({ id, status }) =>
      (await api.post(`/admin/appointments/${id}/status`, { status })).data,
    onSuccess: () => {
      toast.success("Status updated");
      qc.invalidateQueries({ queryKey: ["appointments"] });
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Update failed"),
  });

  const [cancelTarget, setCancelTarget] = useState(null);
  const [cancelReason, setCancelReason] = useState("");
  const [keepSlotBlocked, setKeepSlotBlocked] = useState(false);
  const [eliminateTarget, setEliminateTarget] = useState(null);

  const openCancel = (appt) => {
    setCancelTarget(appt);
    setCancelReason("");
    setKeepSlotBlocked(false);
  };

  const submitCancel = () => {
    cancel.mutate(
      { id: cancelTarget.id, reason: cancelReason, keep_slot_blocked: keepSlotBlocked },
      { onSuccess: () => setCancelTarget(null) }
    );
  };

  const submitEliminate = () => {
    if (!eliminateTarget) return;
    const next = Array.from(new Set([...eliminatedIds, eliminateTarget.id]));
    saveEliminatedIds(next);
    setEliminatedIds(next);
    toast.success("Cancelled appointment eliminated from this list");
    setEliminateTarget(null);
  };

  const exportCsv = async () => {
    const url = new URL(`${API}/admin/appointments/export.csv`);
    Object.entries(params).forEach(([k, v]) => v && url.searchParams.set(k, v));
    try {
      const res = await fetch(url, { headers: { Authorization: `Bearer ${getToken()}` } });
      if (!res.ok) {
        toast.error(`Export failed (${res.status})`);
        return;
      }
      const blob = await res.blob();
      const objUrl = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objUrl;
      a.download = "appointments.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(objUrl);
    } catch (e) {
      toast.error("Export failed");
    }
  };

  const statusVariant = (s) =>
    s === "confirmed"
      ? "default"
      : s === "cancelled"
      ? "destructive"
      : s === "completed"
      ? "secondary"
      : s === "no_show"
      ? "outline"
      : s === "pending"
      ? "outline"
      : "secondary";

  const AppointmentActions = ({ a, mobile = false }) => (
    <>
      {a.status === "cancelled" ? (
        <Button
          data-testid={`admin-appt-eliminate-${a.id}`}
          variant="destructive"
          size="sm"
          onClick={() => setEliminateTarget(a)}
          className={mobile ? "w-full touch-manipulation" : ""}
        >
          <Trash2 className="h-4 w-4 mr-1" /> Eliminate
        </Button>
      ) : (
        <Button
          data-testid={ADMIN.apptCancelBtn(a.id)}
          variant={mobile ? "outline" : "ghost"}
          size="sm"
          onClick={() => openCancel(a)}
          className={mobile ? "w-full touch-manipulation" : ""}
        >
          <X className="h-4 w-4 mr-1" /> Cancel
        </Button>
      )}
    </>
  );

  const StatusSelector = ({ a, mobile = false }) => {
    if (a.status === "cancelled") return null;
    return (
      <Select
        value={a.status}
        onValueChange={(v) => v && updateStatus.mutate({ id: a.id, status: v })}
      >
        <SelectTrigger
          data-testid={`admin-appt-status-select-${a.id}`}
          className={mobile ? "h-10 w-full" : "h-8 w-[130px]"}
        >
          <SelectValue placeholder="Set status" />
        </SelectTrigger>
        <SelectContent>
          {STATUS_OPTIONS.map((s) => (
            <SelectItem key={s} value={s}>{STATUS_LABEL[s]}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-semibold tracking-tight">Appointments</h2>
        <Button data-testid={ADMIN.apptExportCsv} variant="outline" onClick={exportCsv}>
          <Download className="h-4 w-4 mr-2" /> Export CSV
        </Button>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base">Filters</CardTitle></CardHeader>
        <CardContent className="grid grid-cols-1 md:grid-cols-5 gap-3">
          <div>
            <Label className="text-xs">Status</Label>
            <Select value={filters.status} onValueChange={(v) => setFilters({ ...filters, status: v })}>
              <SelectTrigger data-testid={ADMIN.apptStatusFilter}><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All</SelectItem>
                <SelectItem value="pending">Pending</SelectItem>
                <SelectItem value="confirmed">Confirmed</SelectItem>
                <SelectItem value="cancelled">Cancelled</SelectItem>
                <SelectItem value="completed">Completed</SelectItem>
                <SelectItem value="no_show">No-show</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">Service</Label>
            <Select value={filters.service_type} onValueChange={(v) => setFilters({ ...filters, service_type: v })}>
              <SelectTrigger data-testid={ADMIN.apptServiceFilter}><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All</SelectItem>
                {bizQ.data?.service_types?.map((st) => <SelectItem key={st} value={st}>{st}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">From</Label>
            <Input data-testid={ADMIN.apptFromDate} type="date" value={filters.from} onChange={(e) => setFilters({ ...filters, from: e.target.value })} />
          </div>
          <div>
            <Label className="text-xs">To</Label>
            <Input data-testid={ADMIN.apptToDate} type="date" value={filters.to} onChange={(e) => setFilters({ ...filters, to: e.target.value })} />
          </div>
          <div>
            <Label className="text-xs">Search</Label>
            <Input data-testid={ADMIN.apptSearch} placeholder="Name, email, phone, code" value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} />
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-3 md:hidden">
        {visibleItems.length ? (
          visibleItems.map((a) => (
            <Card key={a.id} data-testid={ADMIN.apptRow(a.id)} style={customerCardStyle(a.customer)}>
              <CardContent className="p-4 space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-semibold flex items-center gap-2"><CustomerColorDot customer={a.customer} /> {a.local_date}</div>
                    <div className="text-sm text-stone-600">{fmtTimeBlock(a.local_time_block)}</div>
                  </div>
                  <Badge data-testid={`admin-appt-status-${a.id}`} variant={statusVariant(a.status)}>{STATUS_LABEL[a.status] || a.status}</Badge>
                </div>
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-medium truncate">{a.customer?.full_name}</div>
                    <CustomerPill customer={a.customer} />
                  </div>
                  <div className="text-xs text-stone-500 break-all">{a.customer?.email}</div>
                  <div className="text-xs text-stone-500">{a.customer?.phone}</div>
                  <div className="text-xs text-stone-500">{a.service_type}</div>
                  <div className="text-xs font-mono text-stone-500">{a.confirmation_code}</div>
                </div>
                <div className="rounded-md border bg-stone-50 p-3">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-stone-500">Details</div>
                  <div className="mt-1 whitespace-pre-wrap break-words text-sm text-stone-700">{cleanDescription(a.description)}</div>
                </div>
                {a.needs_approval && a.status === "pending" && (
                  <Badge data-testid={`admin-appt-needs-approval-${a.id}`} variant="outline" className="border-amber-300 bg-amber-50 text-amber-800 text-[10px]">Needs approval</Badge>
                )}
                <div className="flex flex-col gap-2">
                  <StatusSelector a={a} mobile />
                  <AppointmentActions a={a} mobile />
                </div>
              </CardContent>
            </Card>
          ))
        ) : (
          <Card><CardContent className="text-center text-stone-500 py-8">{apptQ.isLoading ? "Loading..." : "No appointments match the filters."}</CardContent></Card>
        )}
      </div>

      <Card className="hidden md:block">
        <CardContent className="p-0 overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Date</TableHead><TableHead>Time</TableHead><TableHead>Service</TableHead><TableHead>Customer</TableHead><TableHead>Details</TableHead><TableHead>Status</TableHead><TableHead>Code</TableHead><TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visibleItems.length ? visibleItems.map((a) => (
                <TableRow key={a.id} data-testid={ADMIN.apptRow(a.id)} style={customerCardStyle(a.customer)}>
                  <TableCell>{a.local_date}</TableCell>
                  <TableCell>{fmtTimeBlock(a.local_time_block)}</TableCell>
                  <TableCell>{a.service_type}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2"><CustomerColorDot customer={a.customer} /><div><div className="font-medium">{a.customer?.full_name}</div><div className="text-xs text-stone-500">{a.customer?.email}</div><div className="text-xs text-stone-500">{a.customer?.phone}</div></div></div>
                  </TableCell>
                  <TableCell className="max-w-[260px] whitespace-pre-wrap break-words text-sm text-stone-700">{cleanDescription(a.description)}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2"><Badge data-testid={`admin-appt-status-${a.id}`} variant={statusVariant(a.status)}>{STATUS_LABEL[a.status] || a.status}</Badge><CustomerPill customer={a.customer} />{a.needs_approval && a.status === "pending" && <Badge data-testid={`admin-appt-needs-approval-${a.id}`} variant="outline" className="border-amber-300 bg-amber-50 text-amber-800 text-[10px]">Needs approval</Badge>}</div>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{a.confirmation_code}</TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-2">
                      <StatusSelector a={a} />
                      <AppointmentActions a={a} />
                    </div>
                  </TableCell>
                </TableRow>
              )) : (
                <TableRow><TableCell colSpan={8} className="text-center text-stone-500 py-8">{apptQ.isLoading ? "Loading..." : "No appointments match the filters."}</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={!!cancelTarget} onOpenChange={(o) => !o && setCancelTarget(null)}>
        <DialogContent data-testid="admin-cancel-dialog">
          <DialogHeader>
            <DialogTitle>Cancel appointment</DialogTitle>
            <DialogDescription>{cancelTarget && <>{cancelTarget.customer?.full_name} · {cancelTarget.local_date} · {fmtTimeBlock(cancelTarget.local_time_block)}</>}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div><Label className="text-xs">Reason (sent to customer)</Label><Textarea data-testid="admin-cancel-reason" rows={3} value={cancelReason} onChange={(e) => setCancelReason(e.target.value)} placeholder="e.g. Crew unavailable due to emergency" /></div>
            <label className="flex items-start gap-2 text-sm"><Checkbox data-testid="admin-cancel-keep-blocked" checked={keepSlotBlocked} onCheckedChange={(v) => setKeepSlotBlocked(!!v)} /><span>Keep this time slot blocked (don't reopen for new bookings).<br /><span className="text-stone-500 text-xs">Leave unchecked to make the slot available again.</span></span></label>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setCancelTarget(null)}>Keep it</Button><Button data-testid={ADMIN.apptCancelConfirm} variant="destructive" disabled={cancel.isPending} onClick={submitCancel}>{cancel.isPending ? "Cancelling..." : "Cancel appointment"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!eliminateTarget} onOpenChange={(o) => !o && setEliminateTarget(null)}>
        <DialogContent data-testid="admin-eliminate-dialog">
          <DialogHeader>
            <DialogTitle>Eliminate cancelled appointment?</DialogTitle>
            <DialogDescription>
              Are you sure you want to eliminate it from the list?
              {eliminateTarget && <span className="block mt-2">{eliminateTarget.customer?.full_name} · {eliminateTarget.local_date} · {fmtTimeBlock(eliminateTarget.local_time_block)}</span>}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEliminateTarget(null)}>Keep it</Button>
            <Button variant="destructive" onClick={submitEliminate}><Trash2 className="h-4 w-4 mr-1" /> Eliminate</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
