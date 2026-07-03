"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { apiMe, type AuthUser, type AuthTenant } from "@/lib/api";

interface AuthState {
  user: AuthUser | null;
  tenant: AuthTenant | null;
  signOut: () => Promise<void>;
  /** Re-fetch the current user + tenant (e.g. to refresh the storage meter after an upload). */
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState>({
  user: null,
  tenant: null,
  signOut: async () => {},
  refresh: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [tenant, setTenant] = useState<AuthTenant | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;

    (async () => {
      const { data } = await supabase.auth.getSession();
      if (!mounted) return;

      if (!data.session) {
        router.push("/login");
        setLoading(false);
        return;
      }

      try {
        const me = await apiMe();
        if (!mounted) return;
        setUser(me.user);
        setTenant(me.tenant);
      } catch {
        if (mounted) router.push("/login");
      } finally {
        if (mounted) setLoading(false);
      }
    })();

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event) => {
      if (event === "SIGNED_OUT") {
        setUser(null);
        setTenant(null);
        router.push("/login");
      }
    });

    return () => {
      mounted = false;
      subscription.unsubscribe();
    };
  }, [router]);

  /** Re-fetch user + tenant so live-changing fields (e.g. storage usage) stay current. */
  const refresh = useCallback(async () => {
    try {
      const me = await apiMe();
      setUser(me.user);
      setTenant(me.tenant);
    } catch {
      // Keep the last known values on a transient failure — don't blank the UI.
    }
  }, []);

  const signOut = async () => {
    await supabase.auth.signOut();
    // onAuthStateChange handles the redirect
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-white">
        <div className="w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <AuthContext.Provider value={{ user, tenant, signOut, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  return useContext(AuthContext);
}
