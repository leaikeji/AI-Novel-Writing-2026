export function compressCover(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!file.type.startsWith("image/")) {
      reject(new Error("请选择图片文件"));
      return;
    }
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("读取图片失败"));
    reader.onload = () => {
      const image = new Image();
      image.onerror = () => reject(new Error("图片格式无法识别"));
      image.onload = () => {
        const canvas = document.createElement("canvas");
        canvas.width = 540;
        canvas.height = 720;
        const context = canvas.getContext("2d");
        if (!context) {
          reject(new Error("当前浏览器无法处理封面"));
          return;
        }
        const sourceRatio = image.width / image.height;
        const targetRatio = 3 / 4;
        let sx = 0;
        let sy = 0;
        let sw = image.width;
        let sh = image.height;
        if (sourceRatio > targetRatio) {
          sw = image.height * targetRatio;
          sx = (image.width - sw) / 2;
        } else {
          sh = image.width / targetRatio;
          sy = (image.height - sh) / 2;
        }
        context.drawImage(image, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
        let value = canvas.toDataURL("image/jpeg", 0.76);
        if (value.length > 170_000) value = canvas.toDataURL("image/jpeg", 0.52);
        if (value.length > 190_000) {
          reject(new Error("封面压缩后仍然过大，请换一张图片"));
          return;
        }
        resolve(value);
      };
      image.src = String(reader.result || "");
    };
    reader.readAsDataURL(file);
  });
}
