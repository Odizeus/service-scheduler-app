import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { ADMIN } from "@/constants/testIds";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

const KEYS = [
  { k: "booking_confirmation_customer", label: "Customer confirmation" },
  { k: "booking_notification_admin", label: "Admin notification" },
  { k: "booking_cancellation_customer", label: "Customer cancellation" },
];

export default function AdminTemplates() {
  const qc = useQueryClient();
  const tplQ = useQuery({
    queryKey: ["templates"],
    queryFn: async () => (await api.get("/admin/business/email-templates")).data,
  });
  const [form, setForm] = useState(null);
  useEffect(() => {
    if (tplQ.data && !form) {
      const copy = {};
      for (const { k } of KEYS) copy[k] = { ...(tplQ.data[k] || { subject: "", body_html: "" }) };
      setForm(copy);
    }
  }, [tplQ.data]); // eslint-disable-line

  const save = useMutation({
    mutationFn: async () => (await api.patch("/admin/business/email-templates", form)).data,
    onSuccess: () => {
      toast.success("Templates saved");
      qc.invalidateQueries({ queryKey: ["templates"] });
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Save failed"),
  });

  if (!form) return <div>Loading...</div>;

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-semibold tracking-tight">Email templates</h2>
      <p className="text-sm text-stone-500">
        Available variables: <code className="text-xs">{"{{customer_name}}"}</code>{" "}
        <code className="text-xs">{"{{service_type}}"}</code>{" "}
        <code className="text-xs">{"{{date}}"}</code>{" "}
        <code className="text-xs">{"{{time_block}}"}</code>{" "}
        <code className="text-xs">{"{{business_name}}"}</code>{" "}
        <code className="text-xs">{"{{business_phone}}"}</code>{" "}
        <code className="text-xs">{"{{confirmation_code}}"}</code>{" "}
        <code className="text-xs">{"{{cancellation_note}}"}</code>
      </p>
      {KEYS.map(({ k, label }) => (
        <Card key={k} data-testid={ADMIN.tplKey(k)}>
          <CardHeader><CardTitle className="text-base">{label}</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <div>
              <Label className="text-xs">Subject</Label>
              <Input value={form[k].subject}
                onChange={(e) => setForm({ ...form, [k]: { ...form[k], subject: e.target.value } })} />
            </div>
            <div>
              <Label className="text-xs">Body (HTML)</Label>
              <Textarea rows={6} value={form[k].body_html}
                onChange={(e) => setForm({ ...form, [k]: { ...form[k], body_html: e.target.value } })} />
            </div>
          </CardContent>
        </Card>
      ))}
      <Button data-testid={ADMIN.tplSave} onClick={() => save.mutate()} disabled={save.isPending}>
        {save.isPending ? "Saving..." : "Save templates"}
      </Button>
    </div>
  );
}
