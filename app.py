import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
from math import radians, cos, sin, asin, sqrt

# 1. SEGURANÇA E MEMÓRIA
MOTORISTAS_AUTORIZADOS = {
    "11972295576": "senha123",
    "11988887777": "entrega2024",
    "ADMIN": "master00" 
}

if 'logado' not in st.session_state: st.session_state['logado'] = False
if 'df_otimizado' not in st.session_state: st.session_state['df_otimizado'] = None

# Funções de Login
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
st.sidebar.write(f"Motorista: {st.session_state['usuario']}")
if st.sidebar.button("Sair"):
    st.session_state['logado'] = False
    st.session_state['df_otimizado'] = None
    st.rerun()

st.title("🚚 Minha Rota Otimizada")

# Captura GPS
loc = get_geolocation()
if not loc:
    st.warning("Ative o GPS para começar.")
    st.stop()

lat_origem = loc['coords']['latitude']
lon_origem = loc['coords']['longitude']

# Upload
arquivo = st.file_uploader("Suba seu arquivo (Excel ou CSV)", type=['csv', 'xlsx'])

# Lógica Matemática
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
        except Exception as e:
            st.error(f"Erro no arquivo: {e}")

# Exibição do Resultado
if st.session_state['df_otimizado'] is not None:
    df_res = st.session_state['df_otimizado']
    
    # Mapa
    m = folium.Map(location=[lat_origem, lon_origem], zoom_start=14)
    trajeto = [[lat_origem, lon_origem]] + df_res[['Latitude', 'Longitude']].values.tolist()
    folium.PolyLine(trajeto, color="#007bff", weight=5).add_to(m)
    folium.Marker([lat_origem, lon_origem], tooltip="Você", icon=folium.Icon(color='red', icon='car', prefix='fa')).add_to(m)
    
    for i, row in enumerate(df_res.itertuples()):
        folium.Marker([row.Latitude, row.Longitude], tooltip=f"Parada {i+1}").add_to(m)
    
    # O CADEADO (Não impede o movimento dos dedos, apenas salva o estado)
    st_folium(m, width="100%", height=500, key="mapa_dinamico")
    
    st.subheader("📋 Lista de Sequência")
    st.dataframe(df_res[['Destination Address', 'Bairro', 'City']])
