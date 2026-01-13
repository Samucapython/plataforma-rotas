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
MOTORISTAS_AUTORIZADOS = {"11972295576": "senha123", "ADMIN": "master00"}

if 'logado' not in st.session_state: st.session_state['logado'] = False
if 'df_otimizado' not in st.session_state: st.session_state['df_otimizado'] = None
if 'entregas_feitas' not in st.session_state: st.session_state['entregas_feitas'] = set()
if 'ver_mapa' not in st.session_state: st.session_state['ver_mapa'] = False

def obter_rota_ruas(coords_list):
    try:
        locs = ";".join([f"{lon},{lat}" for lat, lon in coords_list])
        url = f"http://router.project-osrm.org/route/v1/driving/{locs}?overview=full&geometries=geojson"
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return [[p[1], p[0]] for p in r.json()['routes'][0]['geometry']['coordinates']]
    except: pass
    return coords_list

# Interface de Login
if not st.session_state['logado']:
    st.caption("Acesso Restrito")
    with st.form("login"):
        t = st.text_input("Usuário")
        s = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            if t in MOTORISTAS_AUTORIZADOS and MOTORISTAS_AUTORIZADOS[t] == s:
                st.session_state['logado'] = True
                st.rerun()
    st.stop()

st.set_page_config(page_title="Rota Pro", layout="wide")

if st.session_state['df_otimizado'] is not None:
    st_autorefresh(interval=30000, key="datarefresh")

loc = get_geolocation()
if loc and 'coords' in loc:
    lat_origem, lon_origem = loc['coords']['latitude'], loc['coords']['longitude']
else:
    st.warning("Aguardando GPS...")
    st.stop()

# 2. PROCESSAMENTO (AGORA PRESERVANDO AT, SEQUENCE E TN)
if st.session_state['df_otimizado'] is None:
    st.subheader("🚚 Samuel: Iniciar Rota")
    arquivo = st.file_uploader("Subir planilha", type=['csv', 'xlsx'])
    if arquivo and st.button("CALCULAR MELHOR CAMINHO"):
        df_raw = pd.read_csv(arquivo) if arquivo.name.endswith('.csv') else pd.read_excel(arquivo)
        
        # Agrupamento preservando as colunas que você solicitou
        df = df_raw.groupby(['Latitude', 'Longitude'], as_index=False).agg({
            'AT ID': 'first',
            'Sequence': 'first',
            'SPX TN': 'first',
            'Destination Address': 'first',
            'Bairro': 'first',
            'City': 'first',
            'Stop': 'count'
        })
        
        coords = [[lat_origem, lon_origem]] + df[['Latitude', 'Longitude']].values.tolist()
        manager = pywrapcp.RoutingIndexManager(len(coords), 1, 0)
        routing = pywrapcp.RoutingModel(manager)
        
        def dist_call(f, t):
            p1 = coords[manager.IndexToNode(f)]; p2 = coords[manager.IndexToNode(t)]
            la1, lo1 = map(radians, p1); la2, lo2 = map(radians, p2)
            return int(2 * asin(sqrt(sin((la2-la1)/2)**2 + cos(la1) * cos(la2) * sin((lo2-lo1)/2)**2)) * 6371000)
        
        transit_idx = routing.RegisterTransitCallback(dist_call)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)
        sol = routing.SolveWithParameters(pywrapcp.DefaultRoutingSearchParameters())
        
        if sol:
            idx, ordem = routing.Start(0), []
            while not routing.IsEnd(idx):
                ordem.append(manager.IndexToNode(idx))
                idx = sol.Value(routing.NextVar(idx))
            st.session_state['df_otimizado'] = df.iloc[[i-1 for i in ordem if i > 0]].copy()
            st.rerun()

# 3. INTERFACE DE GESTÃO (ABAS E BOTÃO MAPA)
if st.session_state['df_otimizado'] is not None:
    df_res = st.session_state['df_otimizado']
    
    # Abas de Status (Focando em Pendente)
    aba_pendente, aba_outros = st.tabs(["⏳ Pendente", "📦 Outros"])
    
    with aba_pendente:
        # Alternador de Visualização
        if not st.session_state['ver_mapa']:
            if st.button("🗺️ MOSTRAR NO MAPA", use_container_width=True):
                st.session_state['ver_mapa'] = True
                st.rerun()
        else:
            if st.button("📋 VOLTAR PARA LISTA", use_container_width=True):
                st.session_state['ver_mapa'] = False
                st.rerun()

        # TELA 1: MAPA (TELA ÚNICA QUANDO ATIVO)
        if st.session_state['ver_mapa']:
            m = folium.Map(location=[lat_origem, lon_origem], zoom_start=16)
            pontos_rota = [[lat_origem, lon_origem]] + df_res[['Latitude', 'Longitude']].values.tolist()
            folium.PolyLine(obter_rota_ruas(pontos_rota), color="#444444", weight=3, opacity=0.6).add_to(m)
            folium.CircleMarker([lat_origem, lon_origem], radius=4, color='red', fill=True).add_to(m)
            
            for i, row in enumerate(df_res.itertuples()):
                cor = "#28a745" if i in st.session_state['entregas_feitas'] else "#212529"
                icone = folium.DivIcon(html=f'<div style="background-color:{cor}; color:white; border-radius:4px; width:20px; height:20px; display:flex; align-items:center; justify-content:center; font-weight:bold; font-size:10px; border:1px solid white;">{i+1}</div>')
                folium.Marker([row.Latitude, row.Longitude], icon=icone).add_to(m)
            
            st_folium(m, width="100%", height=500, key="mapa_full")

        # TELA 2: LISTA E CARD DETALHADO (PADRÃO IMAGEM)
        else:
            proxima = next(((i+1, r) for i, r in enumerate(df_res.itertuples()) if i not in st.session_state['entregas_feitas']), None)
            
            if proxima:
                idx, dados = proxima
                st.markdown("---")
                # Estilo de Card Profissional
                st.warning(f"📍 **PARADA #{idx}**")
                
                col_info1, col_info2 = st.columns(2)
                with col_info1:
                    st.write(f"**AT:** {getattr(dados, 'AT ID', '-')}")
                    st.write(f"**PEDIDO:** {getattr(dados, 'Sequence', '-')}")
                with col_info2:
                    st.write(f"**PARADA:** {idx}")
                    st.write(f"**BR:** {getattr(dados, 'SPX TN', '-')}")
                
                st.info(f"🏠 **ENDEREÇO DESTINATÁRIO:**\n{dados._4}") # _4 é Destination Address no itertuples
                
                # Ações
                c1, c2 = st.columns(2)
                if c1.button("✅ ENTREGAR", use_container_width=True):
                    st.session_state['entregas_feitas'].add(idx-1)
                    st.rerun()
                
                g_maps = f"https://www.google.com/maps/dir/?api=1&origin={lat_origem},{lon_origem}&destination={dados.Latitude},{dados.Longitude}&travelmode=driving"
                c2.link_button("🚀 NAVEGAR", g_maps, use_container_width=True)
            else:
                st.success("🎉 Todas as pendências foram concluídas!")
                if st.button("Finalizar Rota"):
                    st.session_state['df_otimizado'] = None
                    st.rerun()
