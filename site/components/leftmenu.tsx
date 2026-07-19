import React from 'react';

export default function LeftMenu() {
  return (
    // fixed garante que ele flutue na tela sem empurrar o chat
    <div className="fixed left-[5.5%] top-[12%] flex flex-col items-center gap-6 text-[#AEB8CF] z-50">

      <div className="relative flex items-center group">
        <button className="hover:text-[#f1863d] hover:cursor-pointer transition-colors">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-6 h-6">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v6m3-3H9m12 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
          </svg>
        </button>
        <span className="absolute left-10 scale-0 transition-all rounded rounded-[2rem] bg-transparent border border-[1px] border-[#f1863d] p-2 text-xs text-[#f1863d] group-hover:scale-100 whitespace-nowrap shadow-lg">
          Novo Chat
        </span>
      </div>

      <div className="relative flex items-center group">
        <button className="hover:text-[#f1863d] hover:cursor-pointer transition-colors">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-6 h-6">
            <path strokeLinecap="round" strokeLinejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.602 10.602Z" />
          </svg>
        </button>
        <span className="absolute left-10 scale-0 transition-all rounded rounded-[2rem] bg-transparent border border-[1px] border-[#f1863d] p-2 text-xs text-[#f1863d] group-hover:scale-100 whitespace-nowrap shadow-lg">
          Pesquisar histórico
        </span>
      </div>

      <div className="relative flex items-center group">
        <button className="hover:text-[#f1863d] hover:cursor-pointer transition-colors">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-6 h-6 transition-transform duration-500 ease-out group-hover:rotate-90">
            <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.43l-1.003.77a1.119 1.119 0 0 0-.362 1.18c.004.074.006.147.006.222a1.14 1.14 0 0 0 .006.222 1.119 1.119 0 0 0 .362 1.18l1.003.77a1.125 1.125 0 0 1 .26 1.43l-1.296 2.247a1.125 1.125 0 0 1-1.37.49l-1.216-.456a1.125 1.125 0 0 0-1.076.124a6.57 6.57 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281a1.125 1.125 0 0 0-.645-.87a6.528 6.528 0 0 1-.22-.127a1.125 1.125 0 0 0-1.075-.124l-1.217.456a1.125 1.125 0 0 1-1.37-.49l-1.296-2.247a1.125 1.125 0 0 1 .26-1.43l1.003-.77a1.119 1.119 0 0 0 .362-1.18a6.6 6.6 0 0 1-.006-.222c0-.074-.002-.148-.006-.222a1.119 1.119 0 0 0-.362-1.18l-1.003-.77a1.125 1.125 0 0 1-.26-1.43l1.296-2.247a1.125 1.125 0 0 1 1.37-.49l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128c.332-.183.582-.495.644-.869l.213-1.28Z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
          </svg>
        </button>
        <span className="absolute left-10 scale-0 transition-all rounded rounded-[2rem] bg-transparent border border-[1px] border-[#f1863d] p-2 text-xs text-[#f1863d] group-hover:scale-100 whitespace-nowrap shadow-lg">
          Configurações
        </span>
      </div>

    </div>
  );
}