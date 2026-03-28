from playwright.sync_api import sync_playwright
import pandas as pd
import json
import sqlite3
from datetime import datetime

CAMPEONATOS = [
    {"nome": "paulista",   "tournament_id": 372, "season_ids": [69522]},
    {"nome": "carioca",    "tournament_id": 92,  "season_ids": [69574]},
    {"nome": "mineiro",    "tournament_id": 379, "season_ids": [69955]},
    {"nome": "paranaense", "tournament_id": 382, "season_ids": [69576]},
    {"nome": "gaucho",     "tournament_id": 377, "season_ids": [70069]},
]

def calcular_idade(timestamp):
    if not timestamp: return "N/A"
    try:
        if timestamp > 10000000000: timestamp = timestamp / 1000
        nasc = datetime.fromtimestamp(timestamp)
        hoje = datetime.now()
        return hoje.year - nasc.year - ((hoje.month, hoje.day) < (nasc.month, nasc.day))
    except: return "Erro"


def buscar_ids_e_nomes(page, tournament_id, season_ids):
    jogos = []
    ids_vistos = set()

    for season in season_ids:
        print(f"  🔍 Buscando temporada {season}...")

        for r in range(1, 30):
            url = f"https://api.sofascore.com/api/v1/unique-tournament/{tournament_id}/season/{season}/events/round/{r}"
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
                data = json.loads(page.locator("body").inner_text())
                for e in data.get('events', []):
                    if e.get('status', {}).get('type') == 'finished':
                        e_id = str(e['id'])
                        if e_id not in ids_vistos:
                            jogos.append({
                                'id': e_id,
                                'timestamp': e.get('startTimestamp', 0),
                                'home_backup': e['homeTeam']['name'],
                                'away_backup': e['awayTeam']['name']
                            })
                            ids_vistos.add(e_id)
            except: continue

        for bloco in range(0, 11):
            url_bloco = f"https://api.sofascore.com/api/v1/unique-tournament/{tournament_id}/season/{season}/events/last/{bloco}"
            try:
                page.goto(url_bloco, wait_until="networkidle", timeout=30000)
                data = json.loads(page.locator("body").inner_text())
                eventos = data.get('events', [])
                if not eventos: break
                for e in eventos:
                    e_id = str(e['id'])
                    if e.get('status', {}).get('type') == 'finished' and e_id not in ids_vistos:
                        jogos.append({
                            'id': e_id,
                            'timestamp': e.get('startTimestamp', 0),
                            'home_backup': e['homeTeam']['name'],
                            'away_backup': e['awayTeam']['name']
                        })
                        ids_vistos.add(e_id)
            except: break

    return jogos


def extrair_campeonato(page, campeonato):
    nome = campeonato["nome"]
    tournament_id = campeonato["tournament_id"]
    season_ids = campeonato["season_ids"]

    print(f"\n{'='*50}")
    print(f"🏆 Iniciando: {nome.upper()}")
    print(f"{'='*50}")

    jogos = buscar_ids_e_nomes(page, tournament_id, season_ids)
    if not jogos:
        print(f"❌ Nenhum jogo encontrado para {nome}.")
        return None

    print(f"🚀 {len(jogos)} partidas encontradas. Extraindo detalhes...")
    lista_bruta = []

    for i, jogo in enumerate(jogos):
        try:
            page.goto(f"https://api.sofascore.com/api/v1/event/{jogo['id']}/incidents", timeout=30000)
            inc_text = page.locator("body").inner_text()
            inc_data = json.loads(inc_text) if inc_text and inc_text != "{}" else {}

            cartoes_jogo = {}
            for incident in inc_data.get('incidents', []):
                if incident.get('incidentType') == 'card':
                    p_id = incident.get('player', {}).get('id')
                    tipo = incident.get('incidentClass')
                    if p_id:
                        if p_id not in cartoes_jogo:
                            cartoes_jogo[p_id] = {'amarelo': 0, 'vermelho': 0}
                        if tipo == 'yellow':
                            cartoes_jogo[p_id]['amarelo'] += 1
                        elif tipo in ['red', 'yellowRed']:
                            cartoes_jogo[p_id]['vermelho'] += 1

            page.goto(f"https://api.sofascore.com/api/v1/event/{jogo['id']}/lineups", timeout=30000)
            lineup_text = page.locator("body").inner_text()
            if not lineup_text or lineup_text == "{}": continue
            lineup_data = json.loads(lineup_text)

            for lado in ['home', 'away']:
                nome_time = lineup_data.get(lado, {}).get('team', {}).get('name')
                if not nome_time or nome_time == "None":
                    nome_time = jogo['home_backup'] if lado == 'home' else jogo['away_backup']

                players = lineup_data.get(lado, {}).get('players', [])
                for p_data in players:
                    stats = p_data.get('statistics', {})
                    if not stats or stats.get('minutesPlayed', 0) <= 0: continue

                    p_info = p_data.get('player', {})
                    p_id = p_info.get('id')
                    altura_cm = p_info.get('height', 0)
                    altura_m = round(altura_cm / 100, 2) if altura_cm > 0 else 0

                    lista_bruta.append({
                        'player_id': p_id,
                        'nome': p_info.get('name'),
                        'campeonato': nome,
                        'time': nome_time,
                        'nacionalidade': p_info.get('country', {}).get('name', 'N/A'),
                        'posicao': p_data.get('position') or p_info.get('position', 'N/A'),
                        'idade': calcular_idade(p_info.get('dateOfBirthTimestamp')),
                        'altura': altura_m,
                        'valor_mercado': p_info.get('proposedMarketValueRaw', {}).get('value', 0) if p_info.get('proposedMarketValueRaw') else 0,
                        'matches': 1,
                        'cartao_amarelo': cartoes_jogo.get(p_id, {}).get('amarelo', 0),
                        'cartao_vermelho': cartoes_jogo.get(p_id, {}).get('vermelho', 0),
                        'timestamp': jogo['timestamp'],
                        **{k: v for k, v in stats.items() if not isinstance(v, dict)}
                    })

            if (i + 1) % 10 == 0:
                print(f"  ✅ {i+1}/{len(jogos)} jogos processados...")

        except Exception as e:
            print(f"  ⚠️ Pulei o jogo {jogo['id']}: {e}")
            continue

    if not lista_bruta:
        print(f"  ❌ Nenhum dado extraído para {nome}.")
        return None

    print(f"  📊 Consolidando {nome}...")
    df = pd.DataFrame(lista_bruta)

    # Time mais recente dentro do próprio campeonato
    df_ultimo_time = (
        df.sort_values('timestamp', ascending=False)
        .drop_duplicates('player_id')
        [['player_id', 'time']]
        .rename(columns={'time': 'time_atual'})
    )

    # Posição com mais minutos jogados
    df_pos = (
        df.groupby(['player_id', 'posicao'])['minutesPlayed']
        .sum()
        .reset_index()
        .sort_values('minutesPlayed', ascending=False)
        .drop_duplicates('player_id')
        [['player_id', 'posicao']]
        .rename(columns={'posicao': 'pos_oficial'})
    )

    # Colunas que não entram na soma
    cols_meta = {'player_id', 'nome', 'campeonato', 'time', 'posicao',
                 'idade', 'nacionalidade', 'altura', 'timestamp'}

    agg_rules = {}
    for col in df.columns:
        if col in cols_meta:
            continue
        if col == 'rating':
            agg_rules[col] = 'mean'
        elif col == 'valor_mercado':
            agg_rules[col] = 'max'
        elif col == 'timestamp':
            agg_rules[col] = 'max'
        else:
            agg_rules[col] = 'sum'

    df_final = (
        df.groupby(['player_id', 'nome', 'campeonato', 'idade', 'nacionalidade', 'altura'])
        .agg(agg_rules)
        .reset_index()
    )

    df_final = (
        df_final
        .merge(df_ultimo_time, on='player_id')
        .merge(df_pos, on='player_id')
        .rename(columns={'time_atual': 'time', 'pos_oficial': 'posicao'})
        .round(2)
    )

    # ✅ timestamp agora é mantido na tabela individual
    ordem_bi = ['player_id', 'nome', 'campeonato', 'time', 'nacionalidade', 'posicao',
                'idade', 'altura', 'matches', 'valor_mercado', 'cartao_amarelo', 'cartao_vermelho']
    todas_cols = ordem_bi + [c for c in df_final.columns if c not in ordem_bi]

    print(f"  ✅ {nome} consolidado com {len(df_final)} jogadores.")
    return df_final[todas_cols]


def consolidar_tabela_unica(conn):
    print(f"\n{'='*50}")
    print("🔀 Consolidando tabela única...")
    print(f"{'='*50}")

    dfs = []
    for campeonato in CAMPEONATOS:
        nome = campeonato["nome"]
        try:
            df = pd.read_sql(f"SELECT * FROM {nome}", conn)
            print(f"  ✅ {nome}: {len(df)} jogadores carregados.")
            dfs.append(df)
        except Exception as e:
            print(f"  ⚠️ Não foi possível ler '{nome}': {e}")

    if not dfs:
        print("❌ Nenhuma tabela encontrada. Abortando consolidação.")
        return

    df_todos = pd.concat(dfs, ignore_index=True)
    print(f"\n  Total antes de consolidar: {len(df_todos)} linhas")

    # -------------------------------------------------------
    # 1. Atributos fixos do jogador: pega do registro mais recente
    #    (resolve variações de nome, posição, nacionalidade entre campeonatos)
    # -------------------------------------------------------
    df_mais_recente = (
        df_todos
        .sort_values('timestamp', ascending=False) if 'timestamp' in df_todos.columns
        else df_todos
    )
    df_mais_recente = (
        df_mais_recente
        .drop_duplicates(subset='player_id')
        [['player_id', 'nome', 'nacionalidade', 'posicao', 'idade', 'altura', 'time', 'campeonato']]
    )

    # -------------------------------------------------------
    # 2. Regras de agregação — APENAS pelo player_id
    #    Tudo que não é identidade entra aqui
    # -------------------------------------------------------
    cols_identidade = {'player_id', 'nome', 'campeonato', 'time',
                       'nacionalidade', 'posicao', 'idade', 'altura'}

    agg_rules = {}
    for col in df_todos.columns:
        if col in cols_identidade:
            continue
        if col == 'rating':
            agg_rules[col] = 'mean'
        elif col == 'valor_mercado':
            agg_rules[col] = 'max'
        elif col == 'timestamp':
            agg_rules[col] = 'max'
        else:
            agg_rules[col] = 'sum'

    # Agrupa SOMENTE por player_id — elimina duplicatas independente de posição/nome
    df_stats = (
        df_todos
        .groupby('player_id')
        .agg(agg_rules)
        .reset_index()
    )

    # -------------------------------------------------------
    # 3. Junta atributos fixos com estatísticas agregadas
    # -------------------------------------------------------
    df_consolidado = df_mais_recente.merge(df_stats, on='player_id', how='left')

    # -------------------------------------------------------
    # 4. Ordena colunas para o Power BI
    # -------------------------------------------------------
    ordem_bi = ['player_id', 'nome', 'campeonato', 'time', 'nacionalidade', 'posicao',
                'idade', 'altura', 'matches', 'valor_mercado', 'cartao_amarelo', 'cartao_vermelho']
    todas_cols = ordem_bi + [c for c in df_consolidado.columns if c not in ordem_bi]
    df_consolidado = df_consolidado[[c for c in todas_cols if c in df_consolidado.columns]].round(2)

    df_consolidado.to_sql('todos_campeonatos', conn, if_exists='replace', index=False)
    print(f"\n💾 'todos_campeonatos' criada com {len(df_consolidado)} jogadores únicos.")
    print(f"   (eram {len(df_todos)} linhas antes de consolidar)")

def main():
    conn = sqlite3.connect('estaduais_brasil.db')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for campeonato in CAMPEONATOS:
            df = extrair_campeonato(page, campeonato)
            if df is not None:
                df.to_sql(campeonato["nome"], conn, if_exists='replace', index=False)
                print(f"💾 '{campeonato['nome']}' salvo com {len(df)} jogadores.")
            else:
                print(f"⚠️ '{campeonato['nome']}' não gerou dados, pulando...")

        browser.close()

    # Roda com o banco já populado
    consolidar_tabela_unica(conn)

    conn.close()
    print("\n🎉 Processamento completo! Banco: estaduais_brasil.db")


if __name__ == "__main__":
    main()