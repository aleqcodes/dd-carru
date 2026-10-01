# Carousel Builder

Editor local de carrosséis do Instagram, com até 10 slides de 1080 × 1350 px. Abra `index.html` no navegador para importar imagens/vídeos, ajustar o enquadramento e exportar PNGs, MP4s ou um ZIP.

## Qualidade de vídeo

O encode de navegador usa H.264 `libx264`, preset `veryfast`, CRF 18 e áudio AAC a 128 kbit/s. CRF 18 prioriza qualidade visual; os MP4s podem ficar maiores e demorar mais que o perfil anterior.

## Renderização usando a GPU

`index.html` sozinho roda FFmpeg.wasm no navegador e codifica pela CPU; uma página aberta por `file://` não pode invocar NVENC ou AMF do sistema. Para usar encoders nativos, inicie o helper local:

- **Windows:** instale Python 3 e FFmpeg, depois execute `start-renderer.bat`.
- **Linux:** instale Python 3 e FFmpeg, depois execute `python3 render_server.py` no terminal.

O helper abre `http://127.0.0.1:8765/` e escuta somente no próprio computador. O FFmpeg instalado precisa oferecer `h264_nvenc` para NVIDIA, `h264_amf` para AMD e `libx264` para o fallback por CPU. O renderer tenta NVIDIA, depois AMD e por fim CPU; se um encoder de hardware anunciado pelo FFmpeg falhar durante a codificação, tenta o próximo. A saída usa perfil de qualidade H.264 18. Se o serviço ou o FFmpeg nativo estiver indisponível, vídeos continuam podendo ser exportados pelo FFmpeg.wasm ao abrir `index.html` diretamente.

O modo `file://` e o endereço local `http://127.0.0.1:8765/` têm armazenamentos IndexedDB separados no navegador. Ao trocar de modo, o projeto salvo no outro endereço continua intacto; importe as mídias novamente no novo endereço. A instalação do FFmpeg e do driver compatível com sua GPU é responsabilidade do sistema operacional.
