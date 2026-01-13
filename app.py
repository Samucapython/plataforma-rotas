import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
from math import radians, cos, sin, asin, sqrt
import requests
from streamlit_autorefresh import st_autorefresh

# 1. SEGURANÇA E MEMÓRIA DE ESTADO
MOTORISTAS_AUTORIZADOS = {
    "11972295576": "senha123",
    "11988887777": "entrega2024",
    "ADMIN": "master00" 
}

if 'logado' not in st.session_state: st.session_state['logado'] = False
if 'df_otimizado' not in st.session_state: st.session_state['df_otimizado'] = None
if 'entregas_feitas' not in st.session_state: st.session_state['entregas_feitas'] = set()

# Função para traçar rota pelas ruas (OSRM)
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

# 2. CONFIGURAÇÃO DA PÁGINA E AUTO-REFRESH
st.set_page_config(page_title="Rota Pro", layout="wide")

# Atualiza a posição e checa o Geofencing a cada 30 segundos
if st.session_state['df_otimizado'] is not None:
    st_autorefresh(interval=30000, key="datarefresh")

st.sidebar.write(f"Motorista: {st.session_state['usuario']}")
if st.sidebar.button("Sair"):
    st.session_state['logado'] = False
    st.session_state['df_otimizado'] = None
    st.session_state['entregas_feitas'] = set()
    st.rerun()

st.title("🚚 Minha Rota Inteligente")

# 3. CAPTURA GPS COM VERIFICAÇÃO DE SEGURANÇA (CORREÇÃO DO ERRO NO CELULAR)
loc = get_geolocation()

if loc and 'coords' in loc:
    lat_origem = loc['coords']['latitude']
    lon_origem = loc['coords']['longitude']
else:
    st.warning("📍 Aguardando sinal do GPS... Certifique-se de que a localização está ativa e que você permitiu o acesso no navegador.")
    if st.button("🔄 Tentar Ativar GPS Manualmente"):
        st.rerun()
    st.stop()

# 4. FUNÇÕES DE CÁLCULO
def calcular_distancia(p1, p2):
    lat1, lon1 = p1; lat2, lon2 = p2
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    d = 2 * asin(sqrt(sin((lat2-lat1)/2)**2 + cos(lat1) * cos(lat2) * sin((lon2-lon1)/2)**2))
    return int(d * 6371000)

def otimizar_rota(df, lat_i, lon_i):
    coords = [[lat_i, lon_i]] + df[['Latitude', 'Longitude']].values.tolist()
    manager = pywrapcp.RoutingIndexManager(len(coords), 1, 0)
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

# 5. PROCESSAMENTO DE ARQUIVO
arquivo = st.file_uploader("Suba seu arquivo (Excel ou CSV)", type=['csv', 'xlsx'])

if arquivo:
    if st.button("CALCULAR MELHOR CAMINHO"):
        try:
            df = pd.read_csv(arquivo) if arquivo.name.endswith('.csv') else pd.read_excel(arquivo)
            indices_rota = otimizar_rota(df, lat_origem, lon_origem)
            if indices_rota:
                st.session_state['df_otimizado'] = df.iloc[indices_rota].copy()
                st.session_state['entregas_feitas'] = set()
                st.rerun()
        except Exception as e:
            st.error(f"Erro no arquivo: {e}")

# 6. EXIBIÇÃO E LÓGICA AUTOMÁTICA
if st.session_state['df_otimizado'] is not None:
    df_res = st.session_state['df_otimizado']
    
    # LÓGICA DE GEOFENCING (Baixa Automática)
    for i, row in enumerate(df_res.itertuples()):
        if i not in st.session_state['entregas_feitas']:
            dist = calcular_distancia((lat_origem, lon_origem), (row.Latitude, row.Longitude))
            if dist < 50: # Raio de 50 metros
                st.session_state['entregas_feitas'].add(i)
                st.toast(f"✅ Parada {i+1} concluída!", icon='📍')

    # MONTAGEM DO MAPA
    m = folium.Map(location=[lat_origem, lon_origem], zoom_start=16)
    pontos_rota = [[lat_origem, lon_origem]] + df_res[['Latitude', 'Longitude']].values.tolist()
    folium.PolyLine(obter_rota_ruas(pontos_rota), color="#1a73e8", weight=4, opacity=0.7).add_to(m)
    
    # Motorista (Ponto Vermelho)
    folium.CircleMarker([lat_origem, lon_origem], radius=6, color='red', fill=True, fill_color='red').add_to(m)
    
    # Marcadores Numerados Pequenos
    for i, row in enumerate(df_res.itertuples()):
        cor_status = "#28a745" if i in st.session_state['entregas_feitas'] else "#1a73e8"
        icone = folium.DivIcon(html=f"""
            <div style="background-color:{cor_status}; color:white; border-radius:50%; width:22px; height:22px; 
            display:flex; align-items:center; justify-content:center; font-weight:bold; font-size:10px; border:1px solid white;">
                {i+1}
            </div>""")
        folium.Marker([row.Latitude, row.Longitude], icon=icone).add_to(m)
    
    st_folium(m, width="100%", height=450, key="mapa_final_v9")
    
    # 7. CARD DINÂMICO DE PRÓXIMA ENTREGA
    st.markdown("---")
    proxima = None
    for i, row in enumerate(df_res.itertuples()):
        if i not in st.session_state['entregas_feitas']:
            proxima = (i+1, row)
            break
            
    if proxima:
        idx, dados = proxima
        with st.container():
            st.success(f"📍 **PRÓXIMA PARADA: {idx}**")
            st.subheader(f"{getattr(dados, 'Destination Address', 'Endereço não encontrado')}")
            st.write(f"🏘️ Bairro: {getattr(dados, 'Bairro', '-')} | Cidade: {getattr(dados, 'City', '-')}")
            
            # Botão Google Maps para Navegação
            g_maps = f"https://www.google.com/maps/dir/?api=1&destination={dados.Latitude},{dados.Longitude}"
            st.link_button("🗺️ ABRIR NAVEGAÇÃO (GOOGLE MAPS)", g_maps)
    else:
        st.balloons()
        st.success("🎉 Rota concluída com sucesso!")
