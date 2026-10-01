# Carousel Builder

Editor local de carrosséis do Instagram, com até 10 slides de 1080 × 1350 px. Abra `index.html` no navegador para importar imagens/vídeos, ajustar o enquadramento e exportar PNGs, MP4s ou um ZIP.

## Formatos de imagem

O editor aceita imagens JPG/JPEG, PNG, WebP, HEIC e HEIF como slides. Na primeira importação HEIC/HEIF, baixa sob demanda o conversor `heic2any` pela internet e converte a foto para PNG no próprio navegador. O arquivo convertido é usado na prévia, no salvamento local e na exportação; a foto não é enviada a um servidor. Conexão com a internet é necessária apenas para carregar o conversor na primeira vez. Imagens com múltiplas fotos no mesmo arquivo HEIC não são aceitas.

Overlays continuam aceitando PNG, JPG/JPEG e WebP.

## Posição e tamanho do overlay

Selecione a camada **Overlay** para arrastar sua imagem no slide, ou informe valores de X, Y, largura e altura em pixels do quadro exportado (1080 × 1350). Largura e altura preservam a proporção da imagem. Marque **Editar todos os slides juntos** para aplicar cada alteração de posição/tamanho a todos os slides; desmarque para ajustar somente o slide selecionado. A visibilidade do overlay continua configurável por slide.

## Qualidade de vídeo

O encode de navegador usa H.264 `libx264`, preset `veryfast`, CRF 18 e áudio AAC a 128 kbit/s. CRF 18 prioriza qualidade visual; os MP4s podem ficar maiores e demorar mais que o perfil anterior.

No painel de cada vídeo, **Mutar áudio na exportação** remove a faixa de áudio do MP4 daquele slide. Por padrão, o áudio original continua incluído; a prévia do editor permanece silenciosa.

## Renderização usando a GPU

`index.html` sozinho roda FFmpeg.wasm no navegador e codifica pela CPU; uma página aberta por `file://` não pode invocar NVENC ou AMF do sistema. Para usar encoders nativos, inicie o helper local:

- **Windows:** instale Python 3 e FFmpeg, depois execute `start-renderer.bat`.
- **Linux:** instale Python 3 e FFmpeg, depois execute `python3 render_server.py` no terminal.

O helper abre `http://127.0.0.1:8765/` e escuta somente no próprio computador. O FFmpeg instalado precisa oferecer `h264_nvenc` para NVIDIA, `h264_amf` para AMD e `libx264` para o fallback por CPU. O renderer tenta NVIDIA, depois AMD e por fim CPU; se um encoder de hardware anunciado pelo FFmpeg falhar durante a codificação, tenta o próximo. A saída usa perfil de qualidade H.264 18. Se o serviço ou o FFmpeg nativo estiver indisponível, vídeos continuam podendo ser exportados pelo FFmpeg.wasm ao abrir `index.html` diretamente.

O modo `file://` e o endereço local `http://127.0.0.1:8765/` têm armazenamentos IndexedDB separados no navegador. Ao trocar de modo, o projeto salvo no outro endereço continua intacto; importe as mídias novamente no novo endereço. A instalação do FFmpeg e do driver compatível com sua GPU é responsabilidade do sistema operacional.
