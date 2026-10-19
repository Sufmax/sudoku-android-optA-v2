# =============================================================================
#  Image du devcontainer CodeSandbox — Sudoku Bot + émulateur Android
#
#  Reprend à l'identique la recette ÉPROUVÉE du dépôt « android_emulator » :
#    Ubuntu 22.04 · OpenJDK 17 · Xvfb + x11vnc (-noshm) + noVNC/websockify
#    Android SDK dans /opt/android-sdk · image API 29 x86_64 · SwiftShader
#  et y ajoute ce dont le bot a besoin (Python 3 + venv, Tesseract FR/EN, libs OpenCV).
#
#  Le SDK et l'image système sont « cuits » dans l'image Docker : le premier
#  lancement de run.sh n'a plus rien à télécharger côté Android. L'AVD (données
#  utilisateur, compte Google, jeu installé) vit, lui, dans le workspace
#  persistant (/project/workspace/sudoku-bot/var/android/avd).
# =============================================================================
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV ANDROID_SDK_ROOT=/opt/android-sdk
ENV ANDROID_HOME=/opt/android-sdk
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV DISPLAY=:1
ENV LIBGL_ALWAYS_SOFTWARE=1
ENV HOME=/root
ENV PATH="/opt/android-sdk/emulator:/opt/android-sdk/cmdline-tools/latest/bin:/opt/android-sdk/platform-tools:${PATH}"

# Image système préinstallée (doit correspondre à config/config.yaml › emulator).
#   playstore → system-images;android-29;google_apis_playstore;x86_64  (Play Store natif)
#   aurora    → system-images;android-29;default;x86_64                (recette d'origine + Aurora Store)
ARG ANDROID_API=29
ARG ANDROID_ABI=x86_64
ARG PRELOAD_IMAGES="google_apis_playstore default"

# --- Miroirs APT stables (Azure), comme dans le dépôt d'origine ---------------
RUN sed -i 's|http://archive.ubuntu.com/ubuntu|http://azure.archive.ubuntu.com/ubuntu|g' /etc/apt/sources.list && \
    sed -i 's|http://security.ubuntu.com/ubuntu|http://azure.archive.ubuntu.com/ubuntu|g' /etc/apt/sources.list

# --- Paquets système -----------------------------------------------------------
RUN for i in 1 2 3; do apt-get update --fix-missing && break || sleep 10; done && \
    apt-get install -y --no-install-recommends --fix-missing \
      openjdk-17-jdk-headless \
      xvfb x11vnc novnc websockify \
      libgl1-mesa-glx libgl1-mesa-dri mesa-utils libgles2-mesa libglu1-mesa \
      libpulse0 libx11-6 libx11-xcb1 libxcb1 libxext6 libxi6 libxrender1 libxtst6 \
      libnss3 libxcomposite1 libxcursor1 libxdamage1 libxkbfile1 libasound2 libglib2.0-0 \
      python3 python3-venv python3-pip \
      tesseract-ocr tesseract-ocr-fra tesseract-ocr-eng \
      wget curl unzip git procps lsof psmisc iproute2 net-tools ca-certificates \
      dnsutils iputils-ping xxd jq util-linux \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# --- Android cmdline-tools -----------------------------------------------------
RUN mkdir -p ${ANDROID_SDK_ROOT}/cmdline-tools && \
    wget -q "https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip" -O /tmp/cmdtools.zip && \
    unzip -q /tmp/cmdtools.zip -d /tmp/ct && \
    mv /tmp/ct/cmdline-tools ${ANDROID_SDK_ROOT}/cmdline-tools/latest && \
    rm -rf /tmp/cmdtools.zip /tmp/ct

# --- Paquets SDK : platform-tools, emulator, plateforme, image(s) système ------
RUN yes | sdkmanager --licenses > /dev/null 2>&1 || true && \
    PKGS="platform-tools emulator platforms;android-${ANDROID_API}" && \
    for tag in ${PRELOAD_IMAGES}; do PKGS="$PKGS system-images;android-${ANDROID_API};${tag};${ANDROID_ABI}"; done && \
    for i in 1 2 3; do sdkmanager $PKGS && break || sleep 15; done && \
    chmod -R a+rX ${ANDROID_SDK_ROOT}

RUN mkdir -p /tmp/logs /root/.android
