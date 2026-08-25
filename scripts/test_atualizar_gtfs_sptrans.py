import json
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from scripts import atualizar_gtfs_sptrans as gtfs


class TestParsingGTFS(unittest.TestCase):
    def test_frequencias_preservam_exact_times(self):
        linhas = [
            {
                "trip_id": "estimada",
                "start_time": "06:00:00",
                "end_time": "07:00:00",
                "headway_secs": "600",
                "exact_times": "0",
            },
            {
                "trip_id": "exata",
                "start_time": "24:10:00",
                "end_time": "25:00:00",
                "headway_secs": "300",
                "exact_times": "1",
            },
            {
                "trip_id": "padrao_gtfs",
                "start_time": "08:00:00",
                "end_time": "09:00:00",
                "headway_secs": "900",
                "exact_times": "",
            },
            {
                "trip_id": "fora_do_recorte",
                "start_time": "10:00:00",
                "end_time": "11:00:00",
                "headway_secs": "600",
                "exact_times": "1",
            },
        ]

        resultado = gtfs._indexar_frequencias(
            linhas, {"estimada", "exata", "padrao_gtfs"}
        )

        self.assertEqual(resultado["estimada"][0]["exact_times"], 0)
        self.assertEqual(resultado["exata"][0], {
            "inicio": 24 * 3600 + 10 * 60,
            "fim": 25 * 3600,
            "intervalo": 300,
            "exact_times": 1,
        })
        self.assertEqual(resultado["padrao_gtfs"][0]["exact_times"], 0)
        self.assertNotIn("fora_do_recorte", resultado)

    def test_frequencia_rejeita_exact_times_invalido(self):
        with self.assertRaisesRegex(ValueError, "exact_times inválido"):
            gtfs._indexar_frequencias([{
                "trip_id": "viagem",
                "start_time": "06:00:00",
                "end_time": "07:00:00",
                "headway_secs": "600",
                "exact_times": "2",
            }], {"viagem"})

    def test_excecoes_calendario_sao_filtradas_e_indexadas(self):
        resultado = gtfs._indexar_excecoes_calendario([
            {"service_id": "util", "date": "20260815", "exception_type": "1"},
            {"service_id": "util", "date": "20260816", "exception_type": "2"},
            {"service_id": "fora", "date": "20260815", "exception_type": "1"},
        ], {"util"})

        self.assertEqual(resultado, {
            "util": {"20260815": 1, "20260816": 2}
        })

    def test_calendar_dates_ausente_e_aceito(self):
        memoria = BytesIO()
        with ZipFile(memoria, "w") as arquivo:
            arquivo.writestr("routes.txt", "route_id,route_short_name\n1,8012\n")
        memoria.seek(0)

        with ZipFile(memoria) as arquivo:
            self.assertEqual(
                gtfs._linhas_opcionais(arquivo, "calendar_dates.txt"), []
            )

    @patch.object(gtfs, "MIN_ROTAS_RECORTE", 1)
    @patch.object(gtfs, "MIN_PARADAS_AREA", 1)
    def test_gerar_grava_exact_times_e_excecoes_no_recorte(self):
        arquivos = {
            "routes.txt": (
                "route_id,route_short_name,route_long_name\n"
                "rota,8012-10,Circular de teste\n"
            ),
            "trips.txt": (
                "route_id,service_id,trip_id,direction_id,trip_headsign\n"
                "rota,servico,viagem,0,Cidade Universitária\n"
            ),
            "stops.txt": (
                "stop_id,stop_name,stop_lat,stop_lon\n"
                "p1,Parada de teste,-23.555,-46.730\n"
            ),
            "stop_times.txt": (
                "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                "viagem,06:00:00,06:00:00,p1,1\n"
            ),
            "frequencies.txt": (
                "trip_id,start_time,end_time,headway_secs,exact_times\n"
                "viagem,06:00:00,07:00:00,600,0\n"
            ),
            "calendar.txt": (
                "service_id,monday,tuesday,wednesday,thursday,friday,"
                "saturday,sunday,start_date,end_date\n"
                "servico,1,1,1,1,1,0,0,20260101,20261231\n"
            ),
            "calendar_dates.txt": (
                "service_id,date,exception_type\n"
                "servico,20260815,1\n"
                "servico,20260817,2\n"
            ),
        }

        with TemporaryDirectory() as temporario:
            pasta = Path(temporario)
            entrada = pasta / "gtfs.zip"
            saida = pasta / "recorte.json"
            with ZipFile(entrada, "w") as arquivo:
                for nome, conteudo in arquivos.items():
                    arquivo.writestr(nome, conteudo)

            gtfs.gerar(entrada, saida)
            documento = json.loads(saida.read_text(encoding="utf-8"))

        frequencia = documento["linhas"]["8012"][0]["viagens"][0][
            "frequencias"
        ][0]
        self.assertEqual(frequencia["exact_times"], 0)
        self.assertEqual(documento["excecoes_calendario"], {
            "servico": {"20260815": 1, "20260817": 2}
        })
        self.assertEqual(documento["versao_esquema"], 4)
        self.assertEqual(documento["estatisticas"]["rotas"], 1)
        self.assertEqual(documento["estatisticas"]["paradas_na_area_selecao"], 1)
        self.assertEqual(
            documento["paradas_na_area_selecao"]["p1"]["nome"],
            "Parada de teste",
        )


if __name__ == "__main__":
    unittest.main()
