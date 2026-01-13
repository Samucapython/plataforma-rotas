import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
from math import radians, cos, sin, asin, sqrt
import requests
from streamlit_autorefresh import st_autorefresh # Nova biblioteca para auto-refresh

# 1. SEGURANÇA E MEMÓRIA
MOTORISTAS_AUTORIZADOS = {
    "11972295576": "senha123",
    "11988887777": "entrega2024",
    "ADMIN": "master00" 
}

if 'logado' not in st.session_state: st.session_state['logado'] = False
if 'df_otimizado' not in st.session_state: st.session_state['df_otimizado'] = None

# Função para traçar rota pelas ruas (OSRM - Grátis)
def obter_rota_ruas(coords_list):
    try:
        locs = ";".join([f"{lon},{lat}" for lat, lon in coords_list])
        url = f"http://router.project-osrm.org/route/v1/driving/{locs}?overview=full&geometries=geojson"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            geom = r.json()['routes'][0]['geometry']['coordinates']
            return [[p[1], p[0]] for p in geom]
    except:
        pass
    return coords_list

def login():
    st.title("🔐 Login - Otimizador de Rotas")
    with st.form("login_form"):
        telefone = st.text_input("Celular (DDD + Número)")
        senha = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            if telefone in MOTORISTAS_AUTORIZADOS and MOTORISTAS_AUTORIZADOS[telefone] == senha:
                st.session_state['logado'] = True
                st.session_state['usuario'] = telefone
                st.rerun()
            else:
                st.error("Dados incorretos.")

if not st.session_state['logado']:
    login()
    st.stop()

# 2. CONFIGURAÇÃO APÓS LOGIN
st.set_page_config(page_title="Rota Pro", layout="wide")

# ATUALIZAÇÃO AUTOMÁTICA: Faz o app conferir o GPS a cada 30 segundos
if st.session_state['df_otimizado'] is not None:
    st_autorefresh(interval=30000, key="datarefresh")

st.sidebar.write(f"Motorista: {st.session_state['usuario']}")
if st.sidebar.button("Sair"):
    st.session_state['logado'] = False
    st.session_state['df_otimizado'] = None
    st.rerun()

st.title("🚚 Minha Rota Inteligente")

# Captura GPS
loc = get_geolocation()
if not loc:
    st.warning("📍 Aguardando sinal do GPS... Certifique-se que a localização está ativa.")
    if st.button("🔄 Tentar Ativar GPS Manualmente"):
        st.rerun()
    st.stop()

lat_origem = loc['coords']['latitude']
lon_origem = loc['coords']['longitude']

# Upload
arquivo = st.file_uploader("Suba seu arquivo do Samuel (Excel ou CSV)", type=['csv', 'xlsx'])

# Funções Matemáticas
def calcular_distancia(p1, p2):
    lat1, lon1 = p1; lat2, lon2 = p2
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    d = 2 * asin(sqrt(sin((lat2-lat1)/2)**2 + cos(lat1) * cos(lat2) * sin((lon2-lon1)/2)**2))
    return int(d * 6371000)

def otimizar_rota(df, lat_i, lon_i):
    coords = [[lat_i, lon_i]] + df[['Latitude', 'Longitude']].values.tolist()
    n = len(coords)
    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)
    def distance_callback(from_idx, to_idx):
        return calcular_distancia(coords[manager.IndexToNode(from_idx)], coords[manager.IndexToNode(to_idx)])
    transit_idx = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    solucao = routing.SolveWithParameters(search_params)
    if solucao:
        idx, ordem = routing.Start(0), []
        while not routing.IsEnd(idx):
            ordem.append(manager.IndexToNode(idx))
            idx = solucao.Value(routing.NextVar(idx))
        return [i-1 for i in ordem if i > 0]
    return None

# Processamento
if arquivo:
    if st.button("CALCULAR MELHOR CAMINHO"):
        try:
            df = pd.read_csv(arquivo) if arquivo.name.endswith('.csv') else pd.read_excel(arquivo)
            indices_rota = otimizar_rota(df, lat_origem, lon_origem)
            if indices_rota:
                st.session_state['df_otimizado'] = df.iloc[indices_rota].copy()
                st.rerun()
        except Exception as e:
            st.error(f"Erro no arquivo: {e}")

# Exibição do Resultado Estético
if st.session_state['df_otimizado'] is not None:
    df_res = st.session_state['df_otimizado']
    
    # O mapa agora foca na posição ATUAL do motorista (lat_origem atualiza no refresh)
    m = folium.Map(location=[lat_origem, lon_origem], zoom_start=15)
    
    pontos_para_api = [[lat_origem, lon_origem]] + df_res[['Latitude', 'Longitude']].values.tolist()
    
    # Desenhar rota pelas ruas
    caminho_ruas = obter_rota_ruas(pontos_para_api)
    folium.PolyLine(caminho_ruas, color="#1a73e8", weight=6, opacity=0.8).add_to(m)
    
    # Marcador da posição ATUAL em tempo real
    folium.Marker(
        [lat_origem, lon_origem], 
        tooltip="Sua posição atual", 
        icon=folium.Icon(color='red', icon='car', prefix='fa')
    ).add_to(m)
    
    # Marcadores Numerados
    for i, row in enumerate(df_res.itertuples()):
        icone_numero = folium.DivIcon(html=f"""
            <div style="background-color: #1a73e8; color: white; border-radius: 50%; width: 30px; height: 30px; 
                display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 14px;
                border: 2px solid white; box-shadow: 0px 0px 5px rgba(0,0,0,0.5);">
                {i+1}
            </div>
        """)
        folium.Marker([row.Latitude, row.Longitude], icon=icone_numero).add_to(m)
    
    st_folium(m, width="100%", height=550, key="mapa_v6")
    
    st.subheader("📋 Lista de Próximas Entregas")
    st.table(df_res[['Destination Address', 'Bairro']])
