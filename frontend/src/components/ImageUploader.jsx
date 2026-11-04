import { useState, useRef } from 'react';

/**
 * Drag-and-drop + click-to-browse image uploader.
 * Calls onFileSelected(file) when a valid image is chosen.
 */
export default function ImageUploader({ onFileSelected }) {
  const [dragOver, setDragOver] = useState(false);
  const [preview, setPreview] = useState(null);
  const inputRef = useRef(null);

  const handleFile = (file) => {
    if (!file || !file.type.startsWith('image/')) return;
    setPreview(URL.createObjectURL(file));
    onFileSelected(file);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    handleFile(e.dataTransfer.files[0]);
  };

  const handleChange = (e) => handleFile(e.target.files[0]);

  return (
    <div
      className={`uploader ${dragOver ? 'uploader--dragover' : ''}`}
      onClick={() => inputRef.current.click()}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      role="button"
      tabIndex={0}
      aria-label="Upload car image"
      onKeyDown={(e) => e.key === 'Enter' && inputRef.current.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        onChange={handleChange}
        style={{ display: 'none' }}
        aria-hidden="true"
      />

      {preview ? (
        <img src={preview} alt="Selected car" className="uploader__preview" />
      ) : (
        <div className="uploader__placeholder">
          <span className="uploader__icon">📷</span>
          <p className="uploader__text">Drag &amp; drop a photo of the damage</p>
          <p className="uploader__subtext">or click to browse</p>
        </div>
      )}
    </div>
  );
}
