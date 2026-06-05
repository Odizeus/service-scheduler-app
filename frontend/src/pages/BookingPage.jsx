import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, DEFAULT_SLUG } from "@/lib/api";
import { allowedMonths, fmtTimeBlock, isoWeekday, monthLabel, ymd } from "@/lib/dates";
import { BOOKING } from "@/constants/testIds";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { ChevronLeft, ChevronRight, CalendarDays, Clock, MapPin, Phone, Mail, Globe } from "lucide-react";

export default function BookingPage() {
  const { slug = DEFAULT_SLUG } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const months = useMemo(() => allowedMonths(new Date()), []);
  const [monthIdx, setMonthIdx] = useState(0);
  const cur = months[monthIdx];

  const [selectedDate, setSelectedDate] = useState(null);
  const [selectedSlot, setSelectedSlot] = useState(null);
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    phone: "",
    address: "",
    city: "",
    zip: "",
    county: "",
    service_type: "",
    description: "",
  });

  const bizQ = useQuery({
    queryKey: ["business", slug],
    queryFn: async () => (await api.get(`/public/business/${slug}`)).data,
  });
  const business = bizQ.data;

  const monthStr = `${cur.y}-${String(cur.m).padStart(2, "0")}`;
  const availQ = useQuery({
    enabled: !!business,
    queryKey: ["availability", slug, monthStr],
    queryFn: async () =>
      (await api.get(`/public/business/${slug}/availability`, { params: { month: monthStr } })).data,
  });

  useEffect(() => {
    if (business && !form.service_type && business.service_types?.length) {
      setForm((f) => ({ ...f, service_type: business.service_types[0] }));
    }
  }, [business]); // eslint-disable-line

  const dayMap = useMemo(() => {
    const m = {};
    availQ.data?.days?.forEach((d) => (m[d.date] = d));
    return m;
  }, [availQ.data]);

  const selectedDay = selectedDate ? dayMap[selectedDate] : null;

  const book = useMutation({
    mutationFn: async () => {
      const body = {
        customer: {
          full_name: form.full_name.trim(),
          email: form.email.trim(),
          phone: form.phone.trim(),
          address: form.address.trim(),
          city: form.city.trim() || null,
          zip: form.zip.trim() || null,
          county: form.county.trim() || null,
        },
        service_type: form.service_type,
        description: form.description.trim(),
        local_date: selectedDate,
        local_time_block: selectedSlot,
      };
      return (await api.post(`/public/business/${slug}/appointments`, body)).data;
    },
    onSuccess: (data) => {
      if (data.needs_approval) {
        toast.success("Request received — awaiting approval");
      } else {
        toast.success("Booking confirmed!");
      }
      qc.invalidateQueries({ queryKey: ["availability", slug, monthStr] });
      navigate(`/book/${slug}/confirm/${data.confirmation_code}`);
    },
    onError: (e) => {
      toast.error(e?.response?.data?.detail || "Booking failed");
    },
  });

  const canSubmit =
    selectedDate &&
    selectedSlot &&
    form.service_type &&
    form.full_name.length >= 2 &&
    /.+@.+\..+/.test(form.email) &&
    form.phone.length >= 5 &&
    form.address.length >= 2;

  return (
    <div className="min-h-screen bg-stone-50" data-testid={BOOKING.page}>
      {/* Header */}
      <header className="border-b bg-white">
        <div className="max-w-6xl mx-auto px-6 py-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl md:text-3xl font-semibold tracking-tight text-stone-900">
              {business?.name || "Loading..."}
            </h1>
            <p className="text-sm text-stone-500 mt-1">
              {business?.service_label} · Book in seconds
            </p>
          </div>
          <div className="hidden md:flex items-center gap-6 text-sm text-stone-600">
            {business?.contact_phone && (
              <span className="flex items-center gap-2">
                <Phone className="h-4 w-4" /> {business.contact_phone}
              </span>
            )}
            {business?.contact_email && (
              <span className="flex items-center gap-2">
                <Mail className="h-4 w-4" /> {business.contact_email}
              </span>
            )}
            {business?.website && (
              <a
                href={business.website}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-2 hover:text-stone-900 underline-offset-2 hover:underline"
                data-testid="booking-business-website"
              >
                <Globe className="h-4 w-4" /> Website
              </a>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-10 grid gap-8 md:grid-cols-[1.2fr_1fr]">
        {/* Left: calendar + slots */}
        <Card className="bg-white">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-lg flex items-center gap-2">
                <CalendarDays className="h-5 w-5" />
                Pick a date &amp; time
              </CardTitle>
              <div className="flex items-center gap-2">
                <Button
                  data-testid={BOOKING.monthPrev}
                  variant="outline"
                  size="icon"
                  disabled={monthIdx === 0}
                  onClick={() => {
                    setMonthIdx(0);
                    setSelectedDate(null);
                    setSelectedSlot(null);
                  }}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <div className="text-sm font-medium w-36 text-center">
                  {monthLabel(cur.y, cur.m)}
                </div>
                <Button
                  data-testid={BOOKING.monthNext}
                  variant="outline"
                  size="icon"
                  disabled={monthIdx === 1}
                  onClick={() => {
                    setMonthIdx(1);
                    setSelectedDate(null);
                    setSelectedSlot(null);
                  }}
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
              onSelect={(d) => {
                setSelectedDate(d);
                setSelectedSlot(null);
              }}
            />
            {selectedDay && (
              <div className="mt-6">
                <div className="text-sm font-medium text-stone-700 mb-3 flex items-center gap-2">
                  <Clock className="h-4 w-4" />
                  Available time blocks on {selectedDate}
                </div>
                {selectedDay.slots.length === 0 ? (
                  <p className="text-sm text-stone-500">No slots for this day.</p>
                ) : (
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                    {selectedDay.slots.map((s) => (
                      <Button
                        key={s.time_block}
                        data-testid={BOOKING.slotBtn(s.time_block)}
                        variant={selectedSlot === s.time_block ? "default" : "outline"}
                        disabled={!s.available}
                        onClick={() => setSelectedSlot(s.time_block)}
                        className="justify-center"
                      >
                        {fmtTimeBlock(s.time_block)}
                      </Button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Right: form */}
        <Card className="bg-white">
          <CardHeader>
            <CardTitle className="text-lg">Your details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Service type</Label>
              <Select
                value={form.service_type}
                onValueChange={(v) => setForm({ ...form, service_type: v })}
              >
                <SelectTrigger data-testid={BOOKING.serviceSelect}>
                  <SelectValue placeholder="Select a service" />
                </SelectTrigger>
                <SelectContent>
                  {business?.service_types?.map((st) => (
                    <SelectItem key={st} value={st}>
                      {st}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-1 gap-4">
              <Field label="Full name">
                <Input
                  data-testid={BOOKING.fullName}
                  value={form.full_name}
                  onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                  placeholder="Jane Doe"
                />
              </Field>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <Field label="Email">
                  <Input
                    data-testid={BOOKING.email}
                    type="email"
                    value={form.email}
                    onChange={(e) => setForm({ ...form, email: e.target.value })}
                    placeholder="you@example.com"
                  />
                </Field>
                <Field label="Phone">
                  <Input
                    data-testid={BOOKING.phone}
                    value={form.phone}
                    onChange={(e) => setForm({ ...form, phone: e.target.value })}
                    placeholder="+1 555 123 4567"
                  />
                </Field>
              </div>
              <Field label="Address">
                <Input
                  data-testid={BOOKING.address}
                  value={form.address}
                  onChange={(e) => setForm({ ...form, address: e.target.value })}
                  placeholder="123 Main St"
                />
              </Field>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <Field label="City">
                  <Input
                    data-testid="booking-input-city"
                    value={form.city}
                    onChange={(e) => setForm({ ...form, city: e.target.value })}
                    placeholder="City"
                  />
                </Field>
                <Field label="ZIP">
                  <Input
                    data-testid="booking-input-zip"
                    value={form.zip}
                    onChange={(e) => setForm({ ...form, zip: e.target.value })}
                    placeholder="00000"
                  />
                </Field>
                <Field label="County">
                  <Input
                    data-testid="booking-input-county"
                    value={form.county}
                    onChange={(e) => setForm({ ...form, county: e.target.value })}
                    placeholder="(optional)"
                  />
                </Field>
              </div>
              {business?.service_area &&
                (business.service_area.cities?.length > 0 ||
                  business.service_area.zip_codes?.length > 0 ||
                  business.service_area.counties?.length > 0) && (
                  <div
                    data-testid="booking-service-area-notice"
                    className="text-xs text-stone-500 bg-stone-50 border border-stone-200 rounded p-2"
                  >
                    We service:{" "}
                    {[
                      ...(business.service_area.cities || []),
                      ...(business.service_area.zip_codes || []),
                      ...(business.service_area.counties || []),
                    ]
                      .slice(0, 8)
                      .join(", ")}
                    {business.service_area.out_of_area_policy === "manual_approval" ? (
                      <span> · Outside this area? Bookings require manual approval.</span>
                    ) : (
                      <span> · Outside this area? Bookings cannot be accepted.</span>
                    )}
                  </div>
                )}
              <Field label="Description">
                <Textarea
                  data-testid={BOOKING.description}
                  rows={3}
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  placeholder="Briefly describe what you need..."
                />
              </Field>
            </div>

            <div className="rounded-md bg-stone-50 border border-stone-200 p-3 text-sm">
              {selectedDate ? (
                <>
                  <div className="font-medium text-stone-800 flex items-center gap-2">
                    <CalendarDays className="h-4 w-4" />
                    {selectedDate}
                  </div>
                  <div className="text-stone-600 flex items-center gap-2 mt-1">
                    <Clock className="h-4 w-4" />
                    {selectedSlot ? fmtTimeBlock(selectedSlot) : "Pick a time block"}
                  </div>
                </>
              ) : (
                <p className="text-stone-500">Select a date and time on the left.</p>
              )}
            </div>

            <Button
              data-testid={BOOKING.submit}
              className="w-full"
              disabled={!canSubmit || book.isPending}
              onClick={() => book.mutate()}
            >
              {book.isPending ? "Booking..." : "Confirm booking"}
            </Button>
          </CardContent>
        </Card>
      </main>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

function CalendarGrid({ year, month, dayMap, selectedDate, onSelect }) {
  // build grid; first row offset by ISO weekday of day 1
  const first = new Date(year, month - 1, 1);
  const last = new Date(year, month, 0);
  const lead = (isoWeekday(first) - 1); // Mon=0
  const totalDays = last.getDate();
  const cells = [];
  for (let i = 0; i < lead; i++) cells.push(null);
  for (let d = 1; d <= totalDays; d++) cells.push(new Date(year, month - 1, d));

  const weekdayHeads = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  return (
    <div data-testid={BOOKING.calendar}>
      <div className="grid grid-cols-7 gap-1 text-xs text-stone-500 mb-2">
        {weekdayHeads.map((w) => (
          <div key={w} className="text-center">{w}</div>
        ))}
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
              data-testid={BOOKING.dayBtn(ds)}
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
      <div className="mt-3 flex items-center gap-3 text-xs text-stone-500">
        <Badge variant="outline" className="font-normal">Available</Badge>
        <span className="text-stone-300">|</span>
        <span>Faded = unavailable</span>
      </div>
    </div>
  );
}
