function rotular(url: string): string {
    try {
        const { hostname, pathname } = new URL(url);
        const host = hostname.replace(/^www\./, "");
        const caminho = pathname.replace(/\/+$/, "");
        return caminho ? `${host}${caminho}` : host;
    } catch {
        return url;
    }
}

export default function Fontes({ urls }: { urls: string[] }) {
    if (urls.length === 0) return null;

    return (
        <div className="mt-5">
            <p className="mb-2 font-roboto text-sm text-muted-foreground">Fontes consultadas</p>
            <ul className="flex flex-wrap gap-2">
                {urls.map((url) => (
                    <li key={url} className="min-w-0 max-w-full">
                        <a
                            href={url}
                            target="_blank"
                            rel="noopener noreferrer"
                            title={url}
                            className="glass flex min-w-0 items-center gap-1.5 rounded-full px-3.5 py-1.5 font-roboto text-sm text-muted-foreground transition-colors hover:text-brand"
                        >
                            <svg
                                aria-hidden
                                viewBox="0 0 24 24"
                                fill="none"
                                stroke="currentColor"
                                strokeWidth={2}
                                className="h-3.5 w-3.5 shrink-0 text-brand"
                            >
                                <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    d="M13.5 6H18a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2v-4.5"
                                />
                                <path strokeLinecap="round" strokeLinejoin="round" d="M20 4l-9 9M20 4h-5m5 0v5" />
                            </svg>
                            <span className="truncate">{rotular(url)}</span>
                        </a>
                    </li>
                ))}
            </ul>
        </div>
    );
}
