"use client";
import { useEffect } from "react";

/* Publica em custom properties do <html> o que o CSS não consegue medir:

   --app-height  altura do visual viewport, a única medida que encolhe quando
                 o teclado virtual abre
   --app-offset  quanto o navegador empurrou o visual viewport para cima
                 (o iOS faz isso ao focar um campo perto do rodapé)

   O CSS combina isso com min(100svh, ...) — ver .app-shell em globals.css.
   Nada aqui tenta adivinhar a altura da barra de endereço: medir isso pelo
   window.innerHeight dava valores errados no Android. */
export function useJanelaVisual() {
    useEffect(() => {
        const janela = window.visualViewport;
        if (!janela) return;

        const raiz = document.documentElement;

        /* Altura do viewport com o teclado FECHADO, que é a escala em que o
           backdrop é desenhado. Só cresce: se acompanhasse o encolhimento do
           teclado, o gradiente reescalaria e os brilhos subiriam junto com o
           composer. Zera ao girar o aparelho, quando a tela realmente muda. */
        let maiorAltura = 0;

        const sincronizar = () => {
            /* Sob pinch zoom o visual viewport encolhe sem que nada tenha
               mudado no layout; encolher a casca junto seria pior. A margem
               existe porque em repouso alguns aparelhos reportam scale com
               ruído de arredondamento (1.0000001) — comparar com > 1 puro
               fazia a medida nunca ser publicada. */
            if (janela.scale > 1.05) return;

            const altura = Math.round(janela.height);
            raiz.style.setProperty("--app-height", `${altura}px`);
            raiz.style.setProperty("--app-offset", `${Math.round(janela.offsetTop)}px`);

            if (altura > maiorAltura) {
                maiorAltura = altura;
                raiz.style.setProperty("--backdrop-h", `${altura}px`);
            }
        };

        const aoGirar = () => {
            maiorAltura = 0;
            sincronizar();
        };

        sincronizar();

        janela.addEventListener("resize", sincronizar);
        janela.addEventListener("scroll", sincronizar);
        window.addEventListener("orientationchange", aoGirar);
        return () => {
            janela.removeEventListener("resize", sincronizar);
            janela.removeEventListener("scroll", sincronizar);
            window.removeEventListener("orientationchange", aoGirar);
        };
    }, []);
}

/* Publica a altura de um elemento em uma custom property do <html>, para que
   o CSS possa se posicionar em relação a ele (o dissolvido atrás do composer). */
export function useAlturaPublicada(
    ref: React.RefObject<HTMLElement | null>,
    propriedade: string,
) {
    useEffect(() => {
        const el = ref.current;
        if (!el) return;

        const raiz = document.documentElement;
        const medir = () => raiz.style.setProperty(propriedade, `${el.offsetHeight}px`);

        medir();
        const observador = new ResizeObserver(medir);
        observador.observe(el);
        return () => {
            observador.disconnect();
            raiz.style.removeProperty(propriedade);
        };
    }, [ref, propriedade]);
}
