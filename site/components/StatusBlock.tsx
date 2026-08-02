"use client";
import { useEffect, useState } from "react";

/* Bloco de estado do modelo durante o streaming */
const FRASES = ["Pensando", "Pensando mais um pouco", "Pensando bastante","Pensando ainda mais"];
const INTERVALO_MS = 6000;

/* Rótulo por ferramenta */
const ROTULOS: Record<string, string> = {
    buscar_documentos: "Pesquisando nos documentos",
    consultar_bandejao: "Consultando cardápio"
};

export default function StatusBlock({ ferramentas }: { ferramentas: string[] }) {
    const [indice, setIndice] = useState(0);

    useEffect(() => {
        const timer = setInterval(() => {
            setIndice((n) => Math.min(n + 1, FRASES.length - 1));
        }, INTERVALO_MS);
        return () => clearInterval(timer);
    }, []);

    const rotulo =
        ferramentas.length > 0
            ? `${ROTULOS[ferramentas[0]] ?? "Usando ferramenta"}`
            : FRASES[indice];

    return (
        <div className="mt-4 flex justify-start first:mt-0">
            <span className="glass rounded-full px-4 py-1.5 font-roboto text-sm text-brand">
                <span className="animate-pulse">{rotulo}</span>
            </span>
        </div>
    );
}
