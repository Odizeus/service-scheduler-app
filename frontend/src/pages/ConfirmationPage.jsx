import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api, DEFAULT_SLUG } from "@/lib/api";
import { BOOKING } from "@/constants/testIds";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fmtTimeBlock } from "@/lib/dates";
import { CheckCircle2 } from "lucide-react";

export default function ConfirmationPage() {
  const { slug = DEFAULT_SLUG, code } = useParams();
  const { data, isLoading, error } = useQuery({
    queryKey: ["appt", code],
    queryFn: async () => (await api.get(`/public/appointments/${code}`)).data,
  });

  return (
    <div className="min-h-screen bg-stone-50 flex items-center justify-center px-6 py-12">
      <Card className="w-full max-w-lg bg-white" data-testid={BOOKING.confirmation}>
        <CardHeader>
          <div className="flex items-center gap-3">
            <CheckCircle2 className="h-7 w-7 text-emerald-600" />
            <CardTitle className="text-xl">Booking confirmed</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {isLoading && <p className="text-stone-500">Loading...</p>}
          {error && <p className="text-rose-600">Could not find this booking.</p>}
          {data && (
            <>
              <Row label="Confirmation code" value={data.confirmation_code} mono />
              <Row label="Status" value={data.status} />
              <Row label="Service" value={data.service_type} />
              <Row label="Date" value={data.local_date} />
              <Row label="Time" value={fmtTimeBlock(data.local_time_block)} />
              <Row label="Name" value={data.customer.full_name} />
              <Row label="Business" value={data.business.name} />
              {data.business.contact_phone && (
                <Row label="Contact" value={data.business.contact_phone} />
              )}
              {data.business.contact_email && (
                <Row label="Email" value={data.business.contact_email} />
              )}
              {data.business.website && (
                <Row label="Website" value={data.business.website} />
              )}
            </>
          )}
          <div className="pt-2">
            <Link to={`/book/${slug}`}>
              <Button variant="outline" className="w-full">
                Book another
              </Button>
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Row({ label, value, mono }) {
  return (
    <div className="flex items-start justify-between gap-4 text-sm">
      <span className="text-stone-500">{label}</span>
      <span className={"text-stone-900 text-right " + (mono ? "font-mono" : "")}>{value}</span>
    </div>
  );
}
