import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
from math import radians, cos, sin, asin, sqrt

# --- CONFIGURAÇÃO DE SEGURANÇA (Sua lista de controle) ---
# Aqui você adiciona os números de quem pode acessar (somente números, sem espaços)
MOTORISTAS_AUTORIZADOS = {
    "11972295576": "senha123",
    "11988887777": "entrega2024",
    "ADMIN": "master00" # Sua conta de teste
}

def login():
    st.title("🔐 Acesso Restrito - Motoristas")
    with st.form("login_form"):
        telefone = st.text_input("Número do Celular (com DDD e apenas números)")
        senha = st.text_input("Chave de Acesso", type="password")
        entrar = st.form_submit_button("Acessar Plataforma")
        
        if entrar:
            if telefone in MOTORISTAS_AUTORIZADOS and MOTORISTAS_AUTORIZADOS[telefone] == senha:
                st.session_state['logado'] = True
                st.session_state['usuario'] = telefone
                st.rerun()
            else:
                st.error("❌ Telefone ou Chave incorretos. Fale com o administrador.")

# Inicializa o estado de login
if 'logado' not in st.session_state:
    st.session_state['logado'] = False

if not st.session_state['logado']:
    login()
    st.stop()

# --- DAQUI PARA BAIXO É A PLATAFORMA APÓS O LOGIN ---

st.set_page_config(page_title="Rota Inteligente Pro", layout="wide")
st.sidebar.write(f"Conectado como: {st.session_state['usuario']}")
if st.sidebar.button("Sair"):
    st.session_state['logado'] = False
    st.rerun()

st.title("🚀 Otimizador de Entregas")

# Captura de GPS
st.subheader("1. Sua Localização Atual")
loc = get_geolocation()

if not loc:
    st.info("👋 Por favor, aceite o compartilhamento de localização no seu navegador para traçarmos a rota.")
    st.stop()

lat_origem = loc['coords']['latitude']
lon_origem = loc['coords']['longitude']
st.success(f"📍 GPS Ativo!")

# Upload do Arquivo
st.subheader("2. Carregue seu arquivo de rotas")
arquivo = st.file_uploader("Selecione o arquivo CSV", type=['csv'])

# Funções de Cálculo (Ocultas do usuário)
def calcular_distancia(p1, p2):
    lat1, lon1 = p1
    lat2, lon2 = p2
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    d = 2 * asin(sqrt(sin((lat2-lat1)/2)**2 + cos(lat1) * cos(lat2) * sin((lon2-lon1)/2)**2))
    return int(d * 6371000)

def otimizar(df, lat_i, lon_i):
    coords = [[lat_i, lon_i]] + df[['Latitude', 'Longitude']].values.tolist()
    n = len(coords)
    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)
    def d_cb(f_idx, t_idx):
        return calcular_distancia(coords[manager.IndexToNode(f_idx)], coords[manager.IndexToNode(t_idx)])
    t_idx = routing.RegisterTransitCallback(d_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(t_idx)
    search_p = pywrapcp.DefaultRoutingSearchParameters()
    search_p.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    sol = routing.SolveWithParameters(search_p)
    if sol:
        idx, ordem = routing.Start(0), []
        while not routing.IsEnd(idx):
            ordem.append(manager.IndexToNode(idx))
            idx = sol.Value(routing.NextVar(idx))
        return [i-1 for i in ordem if i > 0]
    return None

if arquivo:
    df = pd.read_csv(arquivo)
    if st.button("🚀 OTIMIZAR MEU CAMINHO AGORA"):
        with st.spinner('Calculando a melhor rota...'):
            seq = otimizar(df, lat_origem, lon_origem)
            if seq:
                df_otimizado = df.iloc[seq].copy()
                
                # Exibição do Mapa
                st.subheader("3. Seu Mapa de Percurso")
                m = folium.Map(location=[lat_origem, lon_origem], zoom_start=14)
                caminho = [[lat_origem, lon_origem]] + df_otimizado[['Latitude', 'Longitude']].values.tolist()
                folium.PolyLine(caminho, color="#007bff", weight=5).add_to(m)
                folium.Marker([lat_origem, lon_origem], tooltip="Início", icon=folium.Icon(color='red')).add_to(m)
                
                for i, row in enumerate(df_otimizado.itertuples()):
                    folium.Marker([row.Latitude, row.Longitude], tooltip=f"Entrega {i+1}").add_to(m)
                
                st_folium(m, width="100%", height=500)
                
                # Lista de Sequência
                st.subheader("📋 Lista de Sequência")
                st.dataframe(df_otimizado[['Destination Address', 'Bairro']])