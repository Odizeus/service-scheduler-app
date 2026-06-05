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

export default function AdminBusiness() {
  const qc = useQueryClient();
  const bizQ = useQuery({
    queryKey: ["business"],
    queryFn: async () => (await api.get("/admin/business")).data,
  });
  const [form, setForm] = useState(null);
  useEffect(() => {
    if (bizQ.data && !form) {
      setForm({
        name: bizQ.data.name,
        service_label: bizQ.data.service_label,
        contact_phone: bizQ.data.contact_phone || "",
        contact_email: bizQ.data.contact_email || "",
        website: bizQ.data.website || "",
        address: bizQ.data.address || { street: "", city: "", state: "", zip: "", country: "US" },
        service_types: (bizQ.data.service_types || []).join("\n"),
        timezone: bizQ.data.timezone || "America/New_York",
        service_area: {
          cities: (bizQ.data.service_area?.cities || []).join("\n"),
          zip_codes: (bizQ.data.service_area?.zip_codes || []).join("\n"),
          counties: (bizQ.data.service_area?.counties || []).join("\n"),
          out_of_area_policy: bizQ.data.service_area?.out_of_area_policy || "block",
        },
      });
    }
  }, [bizQ.data]); // eslint-disable-line

  const save = useMutation({
    mutationFn: async () => {
      const payload = {
        ...form,
        service_types: form.service_types.split("\n").map((s) => s.trim()).filter(Boolean),
        service_area: {
          cities: form.service_area.cities.split("\n").map((s) => s.trim()).filter(Boolean),
          zip_codes: form.service_area.zip_codes.split("\n").map((s) => s.trim()).filter(Boolean),
          counties: form.service_area.counties.split("\n").map((s) => s.trim()).filter(Boolean),
          out_of_area_policy: form.service_area.out_of_area_policy,
        },
      };
      return (await api.patch("/admin/business", payload)).data;
    },
    onSuccess: () => {
      toast.success("Business saved");
      qc.invalidateQueries({ queryKey: ["business"] });
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Save failed"),
  });

  if (!form) return <div>Loading...</div>;

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-semibold tracking-tight">Business settings</h2>
      <Card>
        <CardHeader><CardTitle className="text-base">Identity</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <Label>Business name</Label>
              <Input data-testid={ADMIN.bizName}
                value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
            <div>
              <Label>Service label</Label>
              <Input data-testid={ADMIN.bizServiceLabel}
                value={form.service_label}
                onChange={(e) => setForm({ ...form, service_label: e.target.value })} />
            </div>
            <div>
              <Label>Phone</Label>
              <Input data-testid={ADMIN.bizPhone}
                value={form.contact_phone}
                onChange={(e) => setForm({ ...form, contact_phone: e.target.value })} />
            </div>
            <div>
              <Label>Email</Label>
              <Input data-testid={ADMIN.bizEmail} type="email"
                value={form.contact_email}
                onChange={(e) => setForm({ ...form, contact_email: e.target.value })} />
            </div>
            <div>
              <Label>Website</Label>
              <Input data-testid="admin-biz-website"
                value={form.website}
                placeholder="https://example.com"
                onChange={(e) => setForm({ ...form, website: e.target.value })} />
            </div>
            <div>
              <Label>Timezone (IANA)</Label>
              <Input data-testid="admin-biz-timezone"
                value={form.timezone}
                placeholder="America/New_York"
                onChange={(e) => setForm({ ...form, timezone: e.target.value })} />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Address</CardTitle></CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="sm:col-span-2">
              <Label>Street</Label>
              <Input data-testid={ADMIN.bizStreet}
                value={form.address.street}
                onChange={(e) => setForm({ ...form, address: { ...form.address, street: e.target.value } })} />
            </div>
            <div>
              <Label>City</Label>
              <Input data-testid={ADMIN.bizCity}
                value={form.address.city}
                onChange={(e) => setForm({ ...form, address: { ...form.address, city: e.target.value } })} />
            </div>
            <div>
              <Label>State</Label>
              <Input data-testid={ADMIN.bizState}
                value={form.address.state}
                onChange={(e) => setForm({ ...form, address: { ...form.address, state: e.target.value } })} />
            </div>
            <div>
              <Label>ZIP</Label>
              <Input data-testid={ADMIN.bizZip}
                value={form.address.zip}
                onChange={(e) => setForm({ ...form, address: { ...form.address, zip: e.target.value } })} />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Service types (one per line)</CardTitle></CardHeader>
        <CardContent>
          <Textarea data-testid={ADMIN.bizServiceTypes} rows={6}
            value={form.service_types}
            onChange={(e) => setForm({ ...form, service_types: e.target.value })} />
        </CardContent>
      </Card>

      <Card data-testid="admin-biz-service-area-card">
        <CardHeader>
          <CardTitle className="text-base">Service area</CardTitle>
          <p className="text-xs text-stone-500 mt-1">
            Customers outside this area will be handled per the policy below. Leave all three lists empty to accept any address.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <Label>Cities (one per line)</Label>
              <Textarea data-testid="admin-biz-area-cities" rows={5}
                value={form.service_area.cities}
                onChange={(e) => setForm({ ...form, service_area: { ...form.service_area, cities: e.target.value } })}
                placeholder={"New York\nBrooklyn"} />
            </div>
            <div>
              <Label>ZIP codes (one per line)</Label>
              <Textarea data-testid="admin-biz-area-zips" rows={5}
                value={form.service_area.zip_codes}
                onChange={(e) => setForm({ ...form, service_area: { ...form.service_area, zip_codes: e.target.value } })}
                placeholder={"10001\n10010"} />
            </div>
            <div>
              <Label>Counties (one per line)</Label>
              <Textarea data-testid="admin-biz-area-counties" rows={5}
                value={form.service_area.counties}
                onChange={(e) => setForm({ ...form, service_area: { ...form.service_area, counties: e.target.value } })}
                placeholder={"New York County\nKings County"} />
            </div>
          </div>
          <div>
            <Label>Out-of-area policy</Label>
            <select
              data-testid="admin-biz-area-policy"
              className="mt-1 block w-full md:w-72 rounded-md border border-stone-200 bg-white px-3 py-2 text-sm"
              value={form.service_area.out_of_area_policy}
              onChange={(e) => setForm({ ...form, service_area: { ...form.service_area, out_of_area_policy: e.target.value } })}
            >
              <option value="block">Block booking</option>
              <option value="manual_approval">Require manual approval</option>
            </select>
          </div>
        </CardContent>
      </Card>

      <Button data-testid={ADMIN.bizSave} onClick={() => save.mutate()} disabled={save.isPending}>
        {save.isPending ? "Saving..." : "Save changes"}
      </Button>
    </div>
  );
}
