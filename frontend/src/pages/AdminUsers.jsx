import { useState } from "react";
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
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader,
  AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Trash2, KeyRound } from "lucide-react";

export default function AdminUsers() {
  const qc = useQueryClient();
  const meQ = useQuery({ queryKey: ["me"], queryFn: async () => (await api.get("/admin/me")).data });
  const usersQ = useQuery({
    queryKey: ["users"],
    queryFn: async () => (await api.get("/admin/users")).data,
  });

  const [form, setForm] = useState({ email: "", password: "", role: "staff" });
  const create = useMutation({
    mutationFn: async () => (await api.post("/admin/users", form)).data,
    onSuccess: () => {
      toast.success("User created");
      setForm({ email: "", password: "", role: "staff" });
      qc.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Create failed"),
  });
  const del = useMutation({
    mutationFn: async (id) => (await api.delete(`/admin/users/${id}`)).data,
    onSuccess: () => {
      toast.success("User removed");
      qc.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Delete failed"),
  });

  const [newPw, setNewPw] = useState("");
  const changePw = useMutation({
    mutationFn: async () =>
      (await api.post("/admin/users/me/password", { new_password: newPw })).data,
    onSuccess: () => {
      toast.success("Password changed");
      setNewPw("");
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Change failed"),
  });

  const myId = meQ.data?.user?.id;

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-semibold tracking-tight">Admin users</h2>

      <Card>
        <CardHeader><CardTitle className="text-base">Invite a new admin</CardTitle></CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
            <div>
              <Label className="text-xs">Email</Label>
              <Input data-testid="admin-users-new-email" type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </div>
            <div>
              <Label className="text-xs">Initial password</Label>
              <Input data-testid="admin-users-new-password" type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder="min 8 chars" />
            </div>
            <div>
              <Label className="text-xs">Role</Label>
              <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })}>
                <SelectTrigger data-testid="admin-users-new-role"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="owner">Owner</SelectItem>
                  <SelectItem value="staff">Staff</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-end">
              <Button data-testid="admin-users-create"
                disabled={!form.email || form.password.length < 8 || create.isPending}
                onClick={() => create.mutate()}>
                Add user
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {usersQ.data?.items?.map((u) => (
                <TableRow key={u.id} data-testid={`admin-users-row-${u.id}`}>
                  <TableCell>
                    {u.email}
                    {u.id === myId && <span className="ml-2 text-xs text-stone-500">(you)</span>}
                  </TableCell>
                  <TableCell className="capitalize">{u.role}</TableCell>
                  <TableCell className="text-xs text-stone-500">
                    {u.created_at?.slice(0, 10)}
                  </TableCell>
                  <TableCell className="text-right">
                    {u.id !== myId && (
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button data-testid={`admin-users-delete-${u.id}`} variant="ghost" size="sm">
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>Remove this admin?</AlertDialogTitle>
                            <AlertDialogDescription>
                              They will lose access immediately.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Keep</AlertDialogCancel>
                            <AlertDialogAction onClick={() => del.mutate(u.id)}>
                              Remove
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <KeyRound className="h-4 w-4" /> Change your password
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-3 items-end max-w-md">
            <div className="flex-1">
              <Label className="text-xs">New password</Label>
              <Input data-testid="admin-users-pw-new" type="password" value={newPw}
                onChange={(e) => setNewPw(e.target.value)} placeholder="min 8 chars" />
            </div>
            <Button data-testid="admin-users-pw-save"
              disabled={newPw.length < 8 || changePw.isPending}
              onClick={() => changePw.mutate()}>
              Update
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
