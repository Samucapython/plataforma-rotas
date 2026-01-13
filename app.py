import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
from math import radians, cos, sin, asin, sqrt
import requests
from streamlit_autorefresh import st_autorefresh

# 1. FUNÇÕES DE SUPORTE TÉCNICO
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000 # metros
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi, dlambda = radians(lat2-lat1), radians(lon2-lon1)
    a = sin(dphi/2)**2 + cos(phi1)*cos(phi2)*sin(dlambda/2)**2
    return 2 * R * asin(sqrt(a))

def obter_rota_ruas(coords_list):
    try:
        locs = ";".join([f"{lon},{lat}" for lat, lon in coords_list])
        url = f"http://router.project-osrm.org/route/v1/driving/{locs}?overview=full&geometries=geojson"
        r = requests.get(url, timeout=10)
        return [[p[1], p[0]] for p in r.json()['routes'][0]['geometry']['coordinates']]
    except: return coords_list

# 2. CONFIGURAÇÃO DE ESTADO
st.set_page_config(page_title="Samuel Rota Pro", layout="wide")

if 'logado' not in st.session_state: st.session_state['logado'] = False
if 'df_otimizado' not in st.session_state: st.session_state['df_otimizado'] = None
if 'entregas_feitas' not in st.session_state: st.session_state['entregas_feitas'] = set()
if 'ver_mapa' not in st.session_state: st.session_state['ver_mapa'] = False

# Login simples
if not st.session_state['logado']:
    with st.form("login"):
        u = st.text_input("Usuário")
        s = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            if u in ["ADMIN", "11972295576"]:
                st.session_state['logado'] = True
                st.rerun()
    st.stop()

# GPS em Tempo Real
loc = get_geolocation()
if loc and 'coords' in loc:
    lat_vtr, lon_vtr = loc['coords']['latitude'], loc['coords']['longitude']
else:
    st.warning("📍 Localizando motorista...")
    st.stop()

# 3. PROCESSAMENTO E AGRUPAMENTO (REGRAS DE NEGÓCIO)
if st.session_state['df_otimizado'] is None:
    arquivo = st.file_uploader("Subir Planilha", type=['csv', 'xlsx'])
    if arquivo and st.button("OTIMIZAR TRAJETO"):
        df_raw = pd.read_csv(arquivo) if arquivo.name.endswith('.csv') else pd.read_excel(arquivo)
        
        # Identifica Atribuições (-) vs Entregas (Números)
        df_raw['Is_Atribuicao'] = df_raw['Sequence'].apply(lambda x: 1 if str(x) == '-' else 0)
        
        # AGRUPAMENTO POR ENDEREÇO + COORDENADA (Para evitar paradas duplicadas no mesmo prédio)
        df = df_raw.groupby(['Destination Address', 'Latitude', 'Longitude'], as_index=False).agg({
            'AT ID': 'first',
            'Sequence': lambda x: ", ".join(x.astype(str)), # Junta Sequences (ex: 32, 32)
            'SPX TN': lambda x: "\n".join(x.astype(str)),  # Lista todos os BRs no mesmo endereço
            'Stop': 'first',
            'Is_Atribuicao': 'max' # Se um dos itens for atribuição, o ponto é tratado como tal
        })
        
        # Otimizador de Rota (Priorizando distância e tipo de parada)
        coords = [[lat_vtr, lon_vtr]] + df[['Latitude', 'Longitude']].values.tolist()
        manager = pywrapcp.RoutingIndexManager(len(coords), 1, 0)
        routing = pywrapcp.RoutingModel(manager)
        
        def distance_callback(from_index, to_index):
            p1, p2 = coords[manager.IndexToNode(from_index)], coords[manager.IndexToNode(to_index)]
            return int(haversine(p1[0], p1[1], p2[0], p2[1]))
        
        transit_idx = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)
        sol = routing.SolveWithParameters(pywrapcp.DefaultRoutingSearchParameters())
        
        if sol:
            idx, ordem = routing.Start(0), []
            while not routing.IsEnd(idx):
                ordem.append(manager.IndexToNode(idx))
                idx = sol.Value(routing.NextVar(idx))
            st.session_state['df_otimizado'] = df.iloc[[i-1 for i in ordem if i > 0]].copy()
            st.rerun()

# 4. INTERFACE DE OPERAÇÃO (TELA DO SAMUEL)
if st.session_state['df_otimizado'] is not None:
    st_autorefresh(interval=25000, key="gps_update")
    df_res = st.session_state['df_otimizado']
    
    # Próxima parada que não foi feita
    proxima_idx = next((i for i in range(len(df_res)) if i not in st.session_state['entregas_feitas']), None)

    # AUTO-BAIXA: Verifica se o Samuel chegou no destino
    if proxima_idx is not None:
        p_atual = df_res.iloc[proxima_idx]
        if haversine(lat_vtr, lon_vtr, p_atual.Latitude, p_atual.Longitude) < 35:
            st.session_state['entregas_feitas'].add(proxima_idx)
            st.toast("📍 Parada concluída automaticamente!")
            st.rerun()

    # Alternância de Telas (Lista vs Mapa)
    if not st.session_state['ver_mapa']:
        st.button("🗺️ MOSTRAR NO MAPA", on_click=lambda: st.session_state.update({"ver_mapa":True}), use_container_width=True, type="primary")
        
        if proxima_idx is not None:
            dados = df_res.iloc[proxima_idx]
            st.markdown(f"## 🏁 Parada #{proxima_idx + 1}")
            
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**AT ID:** {dados['AT ID']}")
                st.write(f"**SEQUÊNCIA:** {dados['Sequence']}")
            with col2:
                st.write(f"**TIPO:** {'🏠 ATRIBUIÇÃO' if dados.Is_Atribuicao else '📦 ENTREGA'}")
            
            st.info(f"📍 **ENDEREÇO:**\n{dados['Destination Address']}")
            with st.expander("📦 VER CÓDIGOS BR (SPX TN)", expanded=True):
                st.code(dados['SPX TN'])
            
            g_maps = f"https://www.google.com/maps/dir/?api=1&origin={lat_vtr},{lon_vtr}&destination={dados.Latitude},{dados.Longitude}&travelmode=driving"
            st.link_button("🚀 INICIAR NAVEGAÇÃO", g_maps, use_container_width=True)
            
            if st.button("✅ FINALIZAR MANUALMENTE", use_container_width=True):
                st.session_state['entregas_feitas'].add(proxima_idx)
                st.rerun()
        else:
            st.success("🎉 Rota Finalizada!")
            if st.button("Recomeçar"):
                st.session_state['df_otimizado'] = None
                st.session_state['entregas_feitas'] = set()
                st.rerun()
    else:
        # TELA DE MAPA FULL
        st.button("📋 VOLTAR PARA LISTA", on_click=lambda: st.session_state.update({"ver_mapa":False}), use_container_width=True)
        
        # Cria mapa com inclinação para parecer GPS
        m = folium.Map(location=[lat_vtr, lon_vtr], zoom_start=16, control_scale=True)
        
        # Traça a linha "magnética" nas ruas
        pts = [[lat_vtr, lon_vtr]] + df_res[['Latitude', 'Longitude']].values.tolist()
        folium.PolyLine(obter_rota_ruas(pts), color="#2979FF", weight=5, opacity=0.8).add_to(m)
        
        # Ícone do Motorista
        folium.CircleMarker([lat_vtr, lon_vtr], radius=7, color="red", fill=True, popup="Você").add_to(m)

        # Pontos de Parada
        for i, row in enumerate(df_res.itertuples()):
            foi_feito = i in st.session_state['entregas_feitas']
            cor_ponto = "green" if foi_feito else "blue"
            
            # Se for atribuição (-), usa ícone de casinha
            icon_name = "home" if row.Is_Atribuicao else "info-sign"
            
            folium.Marker(
                [row.Latitude, row.Longitude],
                icon=folium.Icon(color=cor_ponto, icon=icon_name),
                popup=f"Parada {i+1}: {row._1}" # _1 é o endereço
            ).add_to(m)
            
        st_folium(m, width="100%", height=600)
