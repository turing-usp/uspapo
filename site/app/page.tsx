"use client";
import Image from "next/image";
import Navbar from "../components/navbar";
import Leftmenu from "../components/leftmenu";
import ChatResponse from "../components/chatResponse";
import PromptInput from "../components/propmptInput";
import { useState } from "react";

export default function Home() {

  const[pergunta, setPergunta] = useState("");
  const [paginamain, setPaginamain] = useState(true);
  const [historico, setHistorico] = useState({user: "", bot: ""});

  // 2. Função que simula o envio do formulário
  const lidarComEnvio = (e: React.SyntheticEvent) => {
    e.preventDefault();
    if (!pergunta.trim()) return;

    // Ativa a tela de chat e guarda a pergunta digitada
    setPaginamain(false);
    setHistorico({
      user: pergunta,
      bot: `O **Turing USP** é um grupo de extensão universitária fundado e gerido por estudantes da Universidade de São Paulo (USP), focado no estudo, desenvolvimento e disseminação de conhecimentos sobre **Inteligência Artificial (IA)** e **Ciência de Dados (Data Science)**.\n\nO grupo atua como uma ponte entre a academia e o mercado de tecnologia, promovendo a capacitação de seus membros e da comunidade externa por meio de projetos práticos, pesquisas acadêmicas e eventos educativos.\n\n### Áreas de Atuação do Grupo\n\nO grupo se organiza internamente de forma a cobrir diferentes vertentes da computação inteligente. As frentes de estudo e desenvolvimento costumam ser divididas em:\n\n* **Ciência de Dados (Data Science):** Análise exploratória de dados, modelagem estatística, engenharia de recursos (feature engineering) e visualização de dados para extração de conhecimento estruturado. \n Lorem ipsum dolor sit amet, consectetur adipiscing elit. Aliquam at fermentum risus. Suspendisse potenti. Phasellus vitae dui a lacus fringilla lacinia. Sed in tellus tellus. Quisque convallis eget nulla sit amet efficitur. Curabitur id libero sem. Sed faucibus mi sit amet tempor tincidunt. Phasellus sodales libero quis vulputate porta. Phasellus tincidunt velit a lacus eleifend, eu suscipit quam scelerisque. Vivamus vitae nulla non orci malesuada vehicula a ut tortor. Praesent porta volutpat nibh, eget blandit nisi facilisis nec. Sed pretium tortor quis dui pharetra, sed lobortis arcu laoreet. Aliquam at mauris nec eros venenatis vehicula nec non dolor.

Cras a enim et risus interdum cursus et sed urna. Nam dapibus, libero sit amet facilisis eleifend, nibh metus lacinia nibh, id pulvinar nunc odio id risus. Sed id urna interdum, fringilla risus nec, tristique mi. Etiam rhoncus vestibulum ante nec mattis. Duis nec massa condimentum, pellentesque libero lobortis, faucibus arcu. Sed ac lorem sed justo placerat pellentesque. Donec id dolor porta, rutrum urna eget, consequat magna. Quisque elit ex, aliquet non consectetur feugiat, iaculis a risus. Mauris quis auctor nisi, et facilisis nisi.

Nam vitae nibh et arcu vulputate sodales in ultricies risus. Proin eu luctus orci. Curabitur porta dolor eu efficitur viverra. Fusce vitae est ut nisl feugiat molestie. Proin sed leo ut diam luctus laoreet. Donec viverra quis arcu quis tincidunt. Praesent odio nisi, malesuada dignissim sapien eu, elementum feugiat lectus. Aliquam erat volutpat. Nam feugiat egestas sapien sit amet cursus. Lorem ipsum dolor sit amet, consectetur adipiscing elit. In malesuada, libero scelerisque auctor suscipit, velit dolor lacinia metus, ac posuere urna ipsum eu nisl. Duis nec congue nunc. Curabitur pharetra, tortor nec feugiat scelerisque, dui est scelerisque dolor, eu congue nulla nisi et nunc. Praesent euismod volutpat ipsum a vestibulum. Etiam nunc tellus, pellentesque elementum lacus at, vulputate iaculis sem. Pellentesque eu tincidunt arcu.

Aliquam in nisl orci. Suspendisse at leo sit amet ex consequat pharetra. Nam in maximus urna. Phasellus eu purus vel elit iaculis lobortis at convallis turpis. Sed ac sapien vitae tortor tempor consectetur in sit amet nunc. Aenean convallis venenatis tellus, ac tincidunt leo suscipit eu. Nunc pulvinar arcu quis sollicitudin rhoncus. Suspendisse eu purus orci. Mauris vel nisi rhoncus, venenatis nisi non, fermentum quam. Aliquam sit amet ipsum elit. Duis interdum augue eros, a dictum eros ultrices sit amet.

Vivamus sit amet est ut velit euismod eleifend auctor et massa. Sed sagittis est sed lectus dictum, non venenatis felis fermentum. Praesent id enim auctor, cursus dolor sed, porta odio. Proin molestie quam et lacus mollis, eu consequat ex lacinia. Praesent eget magna tempor, vehicula turpis sed, bibendum urna. Donec lobortis dolor nec mi vehicula, ut maximus velit rhoncus. Nunc urna odio, elementum in sapien in, convallis efficitur lectus. Ut ac lobortis ante, sed dictum tellus. Aliquam vitae ex sit amet lacus posuere rhoncus eu sed leo. Curabitur dolor mi, tincidunt eu velit sit amet, porta volutpat ante. Pellentesque dui ex, lobortis quis rutrum id, efficitur vel enim. Ut efficitur metus orci. Aliquam ac luctus turpis, a suscipit erat. Cras placerat diam lectus, id tempor neque volutpat vel.`
    });
    
    setPergunta(""); // Limpa o input
  };

  return (
    <>
      <Navbar>
      </Navbar>
      <Leftmenu>
      </Leftmenu>
        {paginamain ? (
        <>
          <div className="flex flex-col items-center h-[20%] mt-[3%] mx-[5%]">
            <div className="flex flex-row justify-center items-center">
              <Image
                src="/uspapo.png"
                alt=""
                width={60}
                height={60}
              />
              <p className="font-geom text-[3rem] text-[#f1863d] ml-[2%]">USPapo</p>
            </div>
            <p className="font-geom text-[1.25rem] text-[#FFFFFF] mt-[2%]">Seu <span className="font-geom text-[1.25rem] text-[#f1863d]">assistente inteligente</span> para navegar pela USP</p>
          </div>
          <PromptInput value={pergunta} onChange={setPergunta} onSubmit={lidarComEnvio} />
          <div className="flex flex-col items-center mt-[3%] mx-[5%]">
            <p className="font-geom text-[1rem] text-[#ffffff]">Perguntas Frequentes</p>
            <div className="flex flex-row justify-center items-center gap-[2rem] mt-[2%]">
              <button className="flex flex-col justify-center items-center bg-[#FFFFFF]/20 w-[15rem] h-[3rem] rounded-[2rem] border border-[#ffffff] border-[0.05rem] hover:cursor-pointer">
                O que é o USPapo?
              </button>
              <button className="flex flex-col justify-center items-center bg-[#FFFFFF]/20 w-[15rem] h-[3rem] rounded-[2rem] border border-[#ffffff] border-[0.05rem] hover:cursor-pointer">
                O que é o Jupiterweb?
              </button>
              <button className="flex flex-col justify-center items-center bg-[#FFFFFF]/20 w-[15rem] h-[3rem] rounded-[2rem] border border-[#ffffff] border-[0.05rem] hover:cursor-pointer">
              Cardápio de hoje?
              </button>
            </div>
          </div>
          <div className="flex flex-row justify-center items-center mt-[4%] mx-[5%]">
              <p className="font-geom text-[1rem] text-[#f1863d]">Desenvolvido por</p>
              <div className="flex flex-row justify-center items-center ml-[0.5%]">
              <Image
                src="/logo.svg"
                alt=""
                width={30}
                height={30}
              />
              <p className="font-orbitron text-[1rem] text-[#f1863d]">turing.usp</p>
              </div>
          </div>
        </>
        ) : (
          <div>
            <div className="flex flex-col h-[20%] mt-[1%] mr-[20%] ml-[55%]">
              <input 
                type="text" 
                value={historico.user}
                readOnly
                className="bg-[#F5F5F5]/20 text-[#AEB8CF] text-[1.2rem] text-[#FFFFFF] px-[5%] w-[100%] h-[3.5rem] rounded-[2rem]  placeholder:text-[#AEB8CF] focus:outline-none" 
                disabled
                style={{
                boxShadow: 'inset 0 1px 1px rgba(255,255,255,0.4), inset 0 -1px 1px rgba(255,255,255,0.05)'
                }}
                />
            </div>
            <div className="flex flex-col pb-[12%]">
              <ChatResponse text={historico.bot} />
            </div>
            <div className="fixed bottom-0 left-0 right-0 z-20 bg-gradient-to-t from-[#03042c] via-[#03042c]/95 to-transparent pt-8 pb-4">
              <PromptInput value={pergunta} onChange={setPergunta} onSubmit={lidarComEnvio} />
              <p className="mt-[1%] text-center text-[0.875rem] text-[#AEB8CF]">
                O uspapo é uma IA e pode cometer erros. Sempre confirme as informações com fontes oficiais.
              </p>
            </div>
          </div>
        )}
    </>
  );
}
