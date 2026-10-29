import hashlib
import json
import os
import re

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Tự học tiếng Anh từ Shorts Youtube", page_icon="🎬", layout="wide")

CHANNEL_FILE = "chanels.xlsx"
COLUMNS = ["STT", "CHANELID", "CHANELNAME", "SELECTBOX", "DELETE"]
CHAT_MODEL = "qwen/qwen3.8-27b"
STT_MODEL = "whisper-large-v3-turbo"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
COOKIES = {"CONSENT": "YES+1"}

st.title("🎬 Tự học tiếng Anh từ Shorts Youtube")


# ---------------------------------------------------------------- 2. Mật mã
def check_password():
    if st.session_state.get("auth"):
        return
    with st.form("login"):
        pw = st.text_input("Nhập mật mã để đi tiếp", type="password")
        ok = st.form_submit_button("Vào")
    if ok:
        if pw == st.secrets.get("APP_PASSWORD", ""):
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("Sai mật mã.")
    st.stop()


check_password()


# ---------------------------------------------------------------- Groq
@st.cache_resource
def get_groq():
    from groq import Groq
    return Groq(api_key=st.secrets["GROQ_API_KEY"])


def ask_groq(messages, temperature=0.4):
    r = get_groq().chat.completions.create(
        model=CHAT_MODEL, messages=messages, temperature=temperature)
    return r.choices[0].message.content


def transcribe_audio(audio_bytes):
    r = get_groq().audio.transcriptions.create(
        file=("speech.wav", audio_bytes), model=STT_MODEL, language="en")
    return r.text


# ---------------------------------------------------------------- Kênh (xlsx)
def load_channels():
    if os.path.exists(CHANNEL_FILE):
        df = pd.read_excel(CHANNEL_FILE)
        for c in COLUMNS:
            if c not in df.columns:
                df[c] = False if c in ("SELECTBOX", "DELETE") else ""
        df["SELECTBOX"] = df["SELECTBOX"].fillna(False).astype(bool)
        df["DELETE"] = df["DELETE"].fillna(False).astype(bool)
        return df[COLUMNS]
    return pd.DataFrame(columns=COLUMNS)


def save_channels(df):
    df = df.copy()
    df["STT"] = range(1, len(df) + 1)
    df["SELECTBOX"] = False
    df["DELETE"] = False
    df.to_excel(CHANNEL_FILE, index=False)


def extract_video_id(url):
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([\w-]{11})", url)
    return m.group(1) if m else None


def fetch_channel_info(video_url):
    """Từ link video -> (channelId, channelName)."""
    vid = extract_video_id(video_url)
    if not vid:
        raise ValueError("Link không hợp lệ.")
    html = requests.get(f"https://www.youtube.com/watch?v={vid}",
                        headers=UA, cookies=COOKIES, timeout=15).text
    m = (re.search(r'itemprop="channelId" content="(UC[\w-]{22})"', html)
         or re.search(r'"channelId":"(UC[\w-]{22})"', html)
         or re.search(r'"externalChannelId":"(UC[\w-]{22})"', html))
    if not m:
        raise ValueError("Không tìm thấy channelId.")
    name = ""
    try:
        o = requests.get("https://www.youtube.com/oembed",
                         params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"},
                         timeout=15).json()
        name = o.get("author_name", "")
    except Exception:
        pass
    return m.group(1), name or m.group(1)


@st.dialog("Kênh Youtube", width="large")
def channel_dialog():
    df = load_channels()
    if df.empty:
        st.info("Chưa có kênh nào. Hãy dán link một video Youtube để thêm kênh.")
    else:
        st.write("Chọn **một** kênh:")
        edited = st.data_editor(
            df, hide_index=True, use_container_width=True,
            disabled=["STT", "CHANELID", "CHANELNAME"],
            column_config={"SELECTBOX": st.column_config.CheckboxColumn("Chọn"),
                           "DELETE": st.column_config.CheckboxColumn("Xóa")},
            key="chan_editor")
        if st.button("✅ Dùng kênh đã chọn", type="primary"):
            sel = edited[edited["SELECTBOX"] & ~edited["DELETE"]]
            if len(sel) != 1:
                st.warning("Hãy tick đúng 1 kênh.")
            else:
                st.session_state.channel = {"id": sel.iloc[0]["CHANELID"],
                                            "name": sel.iloc[0]["CHANELNAME"]}
                st.session_state.show_dialog = False
                st.rerun()
    if not df.empty:
        c1, c2 = st.columns([1, 2])
        sure = c2.checkbox("Tôi chắc chắn muốn xóa", key="del_sure")
        if c1.button("🗑 Xóa kênh đã đánh dấu"):
            to_del = edited[edited["DELETE"]]
            if to_del.empty:
                st.warning("Chưa tick kênh nào ở cột Xóa.")
            elif not sure:
                st.warning("Hãy tick ô xác nhận trước.")
            else:
                cur = st.session_state.get("channel")
                if cur and cur["id"] in set(to_del["CHANELID"]):
                    st.session_state.pop("channel", None)
                    st.session_state.pop("video", None)
                save_channels(edited[~edited["DELETE"]])
                st.session_state.pop("chan_editor", None)
                st.session_state.pop("del_sure", None)
                st.rerun()
    st.divider()
    link = st.text_input("Dán link video Youtube để thêm kênh mới")
    if st.button("➕ Thêm kênh"):
        try:
            cid, cname = fetch_channel_info(link)
            if cid in df["CHANELID"].values:
                st.warning("Kênh này đã có.")
            else:
                new = pd.DataFrame([[0, cid, cname, False, False]], columns=COLUMNS)
                save_channels(pd.concat([df, new], ignore_index=True))
                st.rerun()
        except Exception as e:
            st.error(f"Lỗi: {e}")


# ---------------------------------------------------------------- Shorts & transcript
@st.cache_data(ttl=600, show_spinner="Đang lấy danh sách shorts...")
def list_shorts(channel_id, limit=24):
    ids = []
    try:
        html = requests.get(f"https://www.youtube.com/channel/{channel_id}/shorts",
                            headers=UA, cookies=COOKIES, timeout=15).text
        ids = list(dict.fromkeys(re.findall(r'"videoId":"([\w-]{11})"', html)))
    except Exception:
        pass
    if not ids:  # dự phòng: RSS (15 video mới nhất, không lọc riêng shorts)
        try:
            xml = requests.get("https://www.youtube.com/feeds/videos.xml",
                               params={"channel_id": channel_id}, timeout=15).text
            ids = list(dict.fromkeys(re.findall(r"<yt:videoId>([\w-]{11})</yt:videoId>", xml)))
        except Exception:
            pass
    return ids[:limit]


@st.cache_data(ttl=3600, show_spinner="Đang lấy phụ đề...")
def get_transcript(video_id):
    from youtube_transcript_api import YouTubeTranscriptApi
    langs = ["en", "en-US", "en-GB"]
    if hasattr(YouTubeTranscriptApi, "get_transcript"):  # bản cũ
        parts = YouTubeTranscriptApi.get_transcript(video_id, languages=langs)
        return " ".join(p["text"] for p in parts)
    fetched = YouTubeTranscriptApi().fetch(video_id, languages=langs)  # bản 1.x
    return " ".join(s.text for s in fetched)


def split_sentences(text):
    text = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(sents) < 3:  # phụ đề không có dấu câu -> cắt theo ~12 từ
        words = text.split()
        sents = [" ".join(words[i:i + 12]) for i in range(0, len(words), 12)]
    return sents


def speak_button(text, label="🔊 Nghe đọc"):
    js_text = json.dumps(re.sub(r"[*#`_>]", "", text).strip())
    components.html(
        "<button id='b' style='padding:6px 14px;border-radius:8px;border:1px solid #ccc;"
        "cursor:pointer;font-size:15px'>" + label + "</button>"
        "<script>document.getElementById('b').onclick=function(){"
        "speechSynthesis.cancel();var u=new SpeechSynthesisUtterance(" + js_text + ");"
        "u.lang='en-US';u.rate=0.9;speechSynthesis.speak(u);};</script>",
        height=45)


# ---------------------------------------------------------------- 3. Chọn kênh
if "channel" not in st.session_state:
    st.session_state.show_dialog = True

with st.sidebar:
    st.header("Kênh")
    if st.session_state.get("channel"):
        st.write(f"**{st.session_state.channel['name']}**")
    if st.button("📺 Chọn / thêm kênh"):
        st.session_state.show_dialog = True
        st.rerun()

if st.session_state.get("show_dialog"):
    channel_dialog()
    st.stop()

channel = st.session_state.channel

# ---------------------------------------------------------------- 4-5. Danh sách shorts
st.subheader(f"Shorts của kênh: {channel['name']}")
ids = list_shorts(channel["id"])
if not ids:
    st.warning("Không lấy được shorts của kênh này.")
    st.stop()

cols = st.columns(6)
for i, vid in enumerate(ids):
    with cols[i % 6]:
        st.image(f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", use_container_width=True)
        if st.button("▶ Phát", key=f"play_{vid}"):
            st.session_state.video = vid

video = st.session_state.get("video")
if not video:
    st.info("Bấm ▶ Phát dưới một short để bắt đầu.")
    st.stop()

# đổi video -> xoá trạng thái học cũ
if st.session_state.get("loaded_video") != video:
    for k in ["summary", "chat", "q_text", "q_feedback", "read_feedback"]:
        st.session_state.pop(k, None)
    st.session_state.loaded_video = video

left, right = st.columns([3, 5])
with left:
    components.html(
        f'<iframe width="315" height="560" src="https://www.youtube.com/embed/{video}?rel=0" '
        'frameborder="0" allow="autoplay; encrypted-media" allowfullscreen></iframe>',
        height=570)

# ---------------------------------------------------------------- 6. Transcript
try:
    transcript = get_transcript(video)
except Exception as e:
    transcript = ""
    with right:
        st.warning(f"Không lấy được phụ đề tự động ({type(e).__name__}). "
                   "Youtube thường chặn IP của máy chủ cloud. Bạn có thể dán văn bản vào bên dưới.")
        transcript = st.text_area("Dán phụ đề (tiếng Anh) của short này", height=150)

if not transcript.strip():
    st.stop()

context = transcript[:12000]
sentences = split_sentences(transcript)

with right:
    with st.expander("📜 Phụ đề gốc"):
        st.write(transcript)

    tab1, tab2, tab3, tab4 = st.tabs(
        ["📝 Tóm tắt / Ghi nhớ", "🎤 Tập đọc", "💬 Hỏi Groq", "❓ Groq hỏi bạn"])

    # ------------------------------------------------------------ 7. Tóm tắt
    with tab1:
        mode = st.radio("Chế độ", ["Tóm tắt", "Ghi nhớ (từ vựng + mẫu câu)"], horizontal=True)
        if st.button("Gửi cho Groq"):
            if mode == "Tóm tắt":
                task = "Summarize the transcript in simple English (B1 level), 3-5 sentences."
            else:
                task = ("List the 8 most useful vocabulary words/phrases and 3 useful sentence "
                        "patterns from the transcript, each with a short English example.")
            task += " After the English part, write a line with only '---' and then a short Vietnamese translation."
            with st.spinner("Groq đang xử lý..."):
                st.session_state.summary = ask_groq([
                    {"role": "system", "content": "You are a friendly English teacher for Vietnamese learners."},
                    {"role": "user", "content": f"{task}\n\nTranscript:\n{context}"}])
        if st.session_state.get("summary"):
            with st.container(border=True):
                st.markdown(st.session_state.summary)
            speak_button(st.session_state.summary.split("---")[0])

    # ------------------------------------------------------------ 8. Tập đọc
    with tab2:
        idx = st.selectbox("Chọn câu", range(len(sentences)),
                           format_func=lambda i: f"{i + 1}. {sentences[i][:70]}")
        target = sentences[idx]
        st.info(target)
        speak_button(target, "🔊 Nghe mẫu")
        audio = st.audio_input("Ghi âm giọng đọc của bạn", key=f"rec_{video}_{idx}")
        typed = st.text_input("…hoặc gõ lại những gì bạn đọc (nếu không ghi âm được)",
                              key=f"typed_{video}_{idx}")
        if st.button("Nhờ Groq đánh giá", key=f"eval_{idx}"):
            spoken = typed
            if audio is not None:
                with st.spinner("Đang nhận dạng giọng nói..."):
                    spoken = transcribe_audio(audio.getvalue())
            if not spoken.strip():
                st.warning("Hãy ghi âm hoặc gõ nội dung bạn đọc.")
            else:
                st.write(f"**Groq nghe được:** {spoken}")
                with st.spinner("Groq đang đánh giá..."):
                    st.session_state.read_feedback = ask_groq([
                        {"role": "system", "content": "You are an English pronunciation and reading coach. "
                         "Reply in Vietnamese, brief and encouraging."},
                        {"role": "user", "content":
                         f"Target sentence: {target}\nWhat the learner said (speech-to-text): {spoken}\n"
                         "Give a score out of 10, list missed/wrong words, and tips to improve."}])
        if st.session_state.get("read_feedback"):
            st.markdown(st.session_state.read_feedback)

    # ------------------------------------------------------------ 9. Hỏi Groq
    with tab3:
        chat = st.session_state.setdefault("chat", [])

        def answer_question(q):
            chat.append({"role": "user", "content": q})
            sys_msg = {"role": "system", "content":
                       "You are an English teacher. Answer ONLY based on this YouTube Short transcript; "
                       "if the answer isn't there, say so. Answer in simple English first. Then write a "
                       "line containing only '---' and after it a short Vietnamese explanation."
                       f"\n\nTranscript:\n{context}"}
            with st.spinner("Groq đang trả lời..."):
                ans = ask_groq([sys_msg] + chat[-10:])
            chat.append({"role": "assistant", "content": ans})

        # --- lịch sử hội thoại, mỗi câu trả lời có nút nghe (chỉ đọc phần tiếng Anh)
        for m in chat:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])
                if m["role"] == "assistant":
                    speak_button(m["content"].split("---")[0], "🔊 Nghe câu trả lời")

        # --- hỏi bằng giọng nói
        n = st.session_state.setdefault("mic_n", 0)
        voice = st.audio_input("🎤 Bấm micro để hỏi bằng tiếng Anh", key=f"mic_{video}_{n}")
        if voice is not None:
            with st.spinner("Đang nhận dạng giọng nói..."):
                spoken = transcribe_audio(voice.getvalue()).strip()
            st.session_state.mic_n += 1  # đổi key để micro được làm mới
            if spoken:
                answer_question(spoken)
            else:
                st.warning("Không nghe rõ, hãy thử lại.")
            st.rerun()

        # --- hoặc gõ chữ
        with st.form("ask_form", clear_on_submit=True):
            q = st.text_input("…hoặc gõ câu hỏi (tiếng Anh hoặc tiếng Việt)")
            sent = st.form_submit_button("Hỏi")
        if sent and q.strip():
            answer_question(q)
            st.rerun()

    # ------------------------------------------------------------ 10. Groq hỏi
    with tab4:
        if st.button("Groq, hãy đặt câu hỏi cho tôi"):
            st.session_state.q_text = ask_groq([
                {"role": "system", "content": "You are an English teacher. Ask ONE short question in English "
                 "about the transcript to check comprehension. Output only the question."},
                {"role": "user", "content": context}], temperature=0.8)
            st.session_state.pop("q_feedback", None)
        if st.session_state.get("q_text"):
            st.info(st.session_state.q_text)
            speak_button(st.session_state.q_text, "🔊 Nghe câu hỏi")
            qkey = hashlib.md5(st.session_state.q_text.encode()).hexdigest()[:8]
            voice4 = st.audio_input("🎤 Bấm micro để trả lời bằng tiếng Anh", key=f"mic4_{video}_{qkey}")
            if voice4 is not None:
                audio_bytes = voice4.getvalue()
                sig = hashlib.md5(audio_bytes).hexdigest()
                if st.session_state.get(f"sig_{qkey}") != sig:  # chỉ nhận dạng khi có bản ghi mới
                    with st.spinner("Đang nhận dạng giọng nói..."):
                        st.session_state[f"ans_{qkey}"] = transcribe_audio(audio_bytes).strip()
                    st.session_state[f"sig_{qkey}"] = sig
                    st.session_state.pop("q_feedback", None)
            ans = st.text_area("Câu trả lời của bạn (có thể sửa lại trước khi nộp)", key=f"ans_{qkey}")
            if st.button("Nộp cho Groq nhận xét"):
                st.session_state.q_feedback = ask_groq([
                    {"role": "system", "content": "You are an English teacher. Comment in Vietnamese on content "
                     "accuracy (versus the transcript), grammar and vocabulary. Then give a corrected "
                     "English version of the learner's answer."},
                    {"role": "user", "content": f"Transcript:\n{context}\n\nQuestion: {st.session_state.q_text}\n"
                                                f"Learner's answer: {ans}"}])
            if st.session_state.get("q_feedback"):
                st.markdown(st.session_state.q_feedback)
