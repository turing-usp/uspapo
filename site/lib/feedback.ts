import { criarCliente } from "./supabase";

export type TipoFeedback = "like" | "dislike";

export type FeedbackItem = {
  id?: string;
  conversa_id: string;
  mensagem_ordem: number;
  tipo: TipoFeedback;
  motivo?: string | null;
  comentario?: string | null;
  created_at?: string;
};

async function uid(): Promise<string | null> {
  try {
    const { data } = await criarCliente().auth.getUser();
    return data.user?.id ?? null;
  } catch {
    return null;
  }
}

function falhou(operacao: string, error: { message: string } | null): boolean {
  if (!error) return false;
  console.error(`[feedback] ${operacao} falhou: ${error.message}`);
  return true;
}

export async function salvarFeedback(params: {
  conversaId: string;
  mensagemOrdem: number;
  tipo: TipoFeedback;
  motivo?: string;
  comentario?: string;
}): Promise<boolean> {
  const usuario = (await uid()) ?? "anonimo";
  const supabase = criarCliente();

  const payload = {
    conversa_id: params.conversaId,
    mensagem_ordem: params.mensagemOrdem,
    user_id: usuario,
    tipo: params.tipo,
    motivo: params.motivo || null,
    comentario: params.comentario || null,
    updated_at: new Date().toISOString(),
  };

  const { error } = await supabase.from("mensagem_feedbacks").upsert(payload, {
    onConflict: "conversa_id,mensagem_ordem,user_id",
  });

  return !falhou("salvarFeedback", error);
}

export async function obterFeedbacksDaConversa(
  conversaId: string
): Promise<Record<number, FeedbackItem>> {
  if (!conversaId) return {};
  const usuario = (await uid()) ?? "anonimo";
  const supabase = criarCliente();

  const { data, error } = await supabase
    .from("mensagem_feedbacks")
    .select("*")
    .eq("conversa_id", conversaId)
    .eq("user_id", usuario);

  if (falhou("obterFeedbacksDaConversa", error) || !data) {
    return {};
  }

  const mapa: Record<number, FeedbackItem> = {};
  for (const item of data) {
    mapa[item.mensagem_ordem] = item;
  }

  return mapa;
}

export async function removerFeedback(params: {
  conversaId: string;
  mensagemOrdem: number;
}): Promise<boolean> {
  const usuario = (await uid()) ?? "anonimo";
  const supabase = criarCliente();

  const { error } = await supabase
    .from("mensagem_feedbacks")
    .delete()
    .eq("conversa_id", params.conversaId)
    .eq("mensagem_ordem", params.mensagemOrdem)
    .eq("user_id", usuario);

  return !falhou("removerFeedback", error);
}
