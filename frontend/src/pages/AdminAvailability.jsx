import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { ADMIN } from "@/constants/testIds";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Trash2 } from "lucide-react";

const DAYS = [
  { n: 1, label: "Mon" }, { n: 2, label: "Tue" }, { n: 3, label: "Wed" },
  { n: 4, label: "Thu" }, { n: 5, label: "Fri" }, { n: 6, label: "Sat" }, { n: 7, label: "Sun" },
];

export default function AdminAvailability() {
  const qc = useQueryClient();
  const bizQ = useQuery({
    queryKey: ["business"],
    queryFn: async () => (await api.get("/admin/business")).data,
  });
  const overridesQ = useQuery({
    queryKey: ["overrides"],
    queryFn: async () => (await api.get("/admin/availability-overrides")).data,
  });

  const [form, setForm] = useState(null);
  useEffect(() => {
    if (bizQ.data && !form) setForm(bizQ.data.availability);
  }, [bizQ.data]); // eslint-disable-line

  const save = useMutation({
    mutationFn: async () =>
      (await api.patch("/admin/business/availability", form)).data,
    onSuccess: () => {
      toast.success("Availability saved");
      qc.invalidateQueries({ queryKey: ["business"] });
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Save failed"),
  });

  const [newOv, setNewOv] = useState({ scope: "day", local_date: "", local_time_block: "", action: "block", reason: "" });
  const addOv = useMutation({
    mutationFn: async () => (await api.post("/admin/availability-overrides", newOv)).data,
    onSuccess: () => {
      toast.success("Block added");
      setNewOv({ scope: "day", local_date: "", local_time_block: "", action: "block", reason: "" });
      qc.invalidateQueries({ queryKey: ["overrides"] });
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Add failed"),
  });
  const delOv = useMutation({
    mutationFn: async (id) => (await api.delete(`/admin/availability-overrides/${id}`)).data,
    onSuccess: () => {
      toast.success("Removed");
      qc.invalidateQueries({ queryKey: ["overrides"] });
    },
  });

  if (!form) return <div>Loading...</div>;

  const toggleDay = (n) => {
    const has = form.working_days.includes(n);
    setForm({
      ...form,
      working_days: has ? form.working_days.filter((d) => d !== n) : [...form.working_days, n].sort(),
    });
  };

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-semibold tracking-tight">Availability</h2>

      <Card>
        <CardHeader><CardTitle className="text-base">Working days &amp; hours</CardTitle></CardHeader>
        <CardContent className="space-y-5">
          <div>
            <Label className="text-xs">Working days</Label>
            <div className="flex flex-wrap gap-3 mt-2">
              {DAYS.map((d) => (
                <label key={d.n} className="flex items-center gap-2 text-sm">
                  <Checkbox
                    data-testid={ADMIN.availDay(d.n)}
                    checked={form.working_days.includes(d.n)}
                    onCheckedChange={() => toggleDay(d.n)}
                  />
                  {d.label}
                </label>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <Label className="text-xs">Day start</Label>
              <Input data-testid={ADMIN.availDayStart} type="time"
                value={form.day_start}
                onChange={(e) => setForm({ ...form, day_start: e.target.value })} />
            </div>
            <div>
              <Label className="text-xs">Day end</Label>
              <Input data-testid={ADMIN.availDayEnd} type="time"
                value={form.day_end}
                onChange={(e) => setForm({ ...form, day_end: e.target.value })} />
            </div>
            <div>
              <Label className="text-xs">Block size</Label>
              <Select
                value={String(form.block_minutes)}
                onValueChange={(v) => setForm({ ...form, block_minutes: parseInt(v, 10) })}
              >
                <SelectTrigger data-testid={ADMIN.availBlockMinutes}><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="60">60 min</SelectItem>
                  <SelectItem value="90">90 min</SelectItem>
                  <SelectItem value="120">120 min (default)</SelectItem>
                  <SelectItem value="180">180 min</SelectItem>
                  <SelectItem value="240">240 min</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <Button data-testid={ADMIN.availSave} onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? "Saving..." : "Save changes"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Blocked dates &amp; slots</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-5 gap-3">
            <div>
              <Label className="text-xs">Scope</Label>
              <Select value={newOv.scope} onValueChange={(v) => setNewOv({ ...newOv, scope: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="day">Whole day</SelectItem>
                  <SelectItem value="slot">Single slot</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Date</Label>
              <Input data-testid={ADMIN.overrideDate} type="date"
                value={newOv.local_date}
                onChange={(e) => setNewOv({ ...newOv, local_date: e.target.value })} />
            </div>
            <div>
              <Label className="text-xs">Time block (slot only)</Label>
              <Input data-testid={ADMIN.overrideSlot} placeholder="HH:MM-HH:MM"
                disabled={newOv.scope !== "slot"}
                value={newOv.local_time_block}
                onChange={(e) => setNewOv({ ...newOv, local_time_block: e.target.value })} />
            </div>
            <div>
              <Label className="text-xs">Reason</Label>
              <Input
                value={newOv.reason}
                onChange={(e) => setNewOv({ ...newOv, reason: e.target.value })} />
            </div>
            <div className="flex items-end">
              <Button data-testid={ADMIN.overrideAdd}
                disabled={!newOv.local_date || (newOv.scope === "slot" && !newOv.local_time_block)}
                onClick={() => addOv.mutate()}>
                Add block
              </Button>
            </div>
          </div>
          <div className="grid gap-6 md:grid-cols-2">
            <div>
              <div className="text-sm font-medium text-stone-700 mb-2" data-testid="blocked-days-heading">
                Blocked days ({(overridesQ.data?.items || []).filter((o) => o.scope === "day" && o.action === "block").length})
              </div>
              <div className="border rounded-md divide-y" data-testid="blocked-days-list">
                {(overridesQ.data?.items || []).filter((o) => o.scope === "day" && o.action === "block").length ? (
                  (overridesQ.data?.items || [])
                    .filter((o) => o.scope === "day" && o.action === "block")
                    .map((o) => (
                      <div
                        key={o.id}
                        data-testid={`blocked-day-row-${o.local_date}`}
                        className="flex items-center justify-between px-4 py-2 text-sm"
                      >
                        <div>
                          <span className="font-medium">{o.local_date}</span>
                          {o.reason && (
                            <span className="ml-2 text-stone-400">— {o.reason}</span>
                          )}
                        </div>
                        <Button
                          data-testid={ADMIN.overrideDelete(o.id)}
                          variant="ghost"
                          size="sm"
                          onClick={() => delOv.mutate(o.id)}
                        >
                          <Trash2 className="h-4 w-4 mr-1" /> Unblock day
                        </Button>
                      </div>
                    ))
                ) : (
                  <div className="text-sm text-stone-500 py-6 text-center">No blocked days.</div>
                )}
              </div>
            </div>
            <div>
              <div className="text-sm font-medium text-stone-700 mb-2" data-testid="blocked-slots-heading">
                Blocked time slots ({(overridesQ.data?.items || []).filter((o) => o.scope === "slot" && o.action === "block").length})
              </div>
              <div className="border rounded-md divide-y" data-testid="blocked-slots-list">
                {(overridesQ.data?.items || []).filter((o) => o.scope === "slot" && o.action === "block").length ? (
                  (overridesQ.data?.items || [])
                    .filter((o) => o.scope === "slot" && o.action === "block")
                    .map((o) => (
                      <div
                        key={o.id}
                        data-testid={`blocked-slot-row-${o.local_date}-${o.local_time_block}`}
                        className="flex items-center justify-between px-4 py-2 text-sm"
                      >
                        <div>
                          <span className="font-medium">{o.local_date}</span>
                          <span className="ml-2 text-stone-500">{o.local_time_block}</span>
                          {o.reason && (
                            <span className="ml-2 text-stone-400">— {o.reason}</span>
                          )}
                        </div>
                        <Button
                          data-testid={ADMIN.overrideDelete(o.id)}
                          variant="ghost"
                          size="sm"
                          onClick={() => delOv.mutate(o.id)}
                        >
                          <Trash2 className="h-4 w-4 mr-1" /> Unblock slot
                        </Button>
                      </div>
                    ))
                ) : (
                  <div className="text-sm text-stone-500 py-6 text-center">No blocked time slots.</div>
                )}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
