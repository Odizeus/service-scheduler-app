import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api, setToken } from "@/lib/api";
import { ADMIN } from "@/constants/testIds";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function AdminLogin() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();

    const cleanEmail = email.trim();
    if (!cleanEmail || !password) {
      toast.error("Enter your email and password.");
      return;
    }

    if (!/.+@.+\..+/.test(cleanEmail)) {
      toast.error("Enter a valid email address.");
      return;
    }

    setLoading(true);
    try {
      const { data } = await api.post("/admin/auth/login", {
        email: cleanEmail,
        password,
      });
      setToken(data.access_token);
      toast.success(`Welcome, ${data.user.email}`);
      navigate("/admin/appointments", { replace: true });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-stone-100 flex items-center justify-center px-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Admin sign in</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            <div className="space-y-2">
              <Label>Email</Label>
              <Input
                data-testid={ADMIN.loginEmail}
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="username"
                required
              />
            </div>
            <div className="space-y-2">
              <Label>Password</Label>
              <Input
                data-testid={ADMIN.loginPassword}
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>
            <Button data-testid={ADMIN.loginSubmit} type="submit" className="w-full" disabled={loading}>
              {loading ? "Signing in..." : "Sign in"}
            </Button>
            <Button asChild type="button" variant="ghost" className="w-full">
              <Link to="/">Back to booking page</Link>
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
