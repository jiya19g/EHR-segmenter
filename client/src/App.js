import React, { useState, useCallback } from 'react';
import styled from 'styled-components';
import { useDropzone } from 'react-dropzone';
import { CSVReader } from 'react-papaparse';
import { FaFileUpload, FaSpinner, FaCheck, FaTimes } from 'react-icons/fa';

const AppContainer = styled.div`
  max-width: 1200px;
  margin: 0 auto;
  padding: 2rem;
  min-height: 100vh;
  background: linear-gradient(135deg, #f5f7fa 0%, #e4e8eb 100%);
`;

const Header = styled.header`
  text-align: center;
  margin-bottom: 3rem;
  padding: 2rem;
  background: white;
  border-radius: 12px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
`;

const Title = styled.h1`
  color: #2d3748;
  font-size: 2.5rem;
  margin-bottom: 1rem;
  font-weight: 700;
`;

const Subtitle = styled.p`
  color: #718096;
  font-size: 1.1rem;
  max-width: 600px;
  margin: 0 auto;
  line-height: 1.6;
`;

const UploadContainer = styled.div`
  background: white;
  border-radius: 12px;
  padding: 2rem;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
  margin-bottom: 2rem;
  transition: all 0.3s ease;
  
  &:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 8px rgba(0, 0, 0, 0.15);
  }
`;

const Dropzone = styled.div`
  border: 2px dashed ${props => props.isDragActive ? '#4299e1' : '#cbd5e0'};
  border-radius: 8px;
  padding: 3rem 2rem;
  text-align: center;
  cursor: pointer;
  transition: all 0.3s ease;
  background: ${props => props.isDragActive ? '#ebf8ff' : 'white'};
  
  &:hover {
    border-color: #4299e1;
    background: #ebf8ff;
  }
`;

const UploadIcon = styled(FaFileUpload)`
  font-size: 3rem;
  color: #4299e1;
  margin-bottom: 1rem;
`;

const UploadText = styled.p`
  color: #4a5568;
  font-size: 1.1rem;
  margin: 0.5rem 0;
`;

const StatusMessage = styled.div`
  margin-top: 1rem;
  padding: 1rem;
  border-radius: 8px;
  background: ${props => {
    if (props.error) return '#fff5f5';
    if (props.success) return '#f0fff4';
    return '#ebf8ff';
  }};
  color: ${props => {
    if (props.error) return '#c53030';
    if (props.success) return '#2f855a';
    return '#2b6cb0';
  }};
  display: flex;
  align-items: center;
  gap: 0.5rem;
`;

const CSVContainer = styled.div`
  background: white;
  border-radius: 12px;
  padding: 2rem;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
  overflow-x: auto;
`;

const Table = styled.table`
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 0.9rem;
  
  th, td {
    padding: 1rem;
    text-align: left;
    border-bottom: 1px solid #e2e8f0;
  }
  
  th {
    background: #f7fafc;
    font-weight: 600;
    color: #2d3748;
    position: sticky;
    top: 0;
    z-index: 10;
  }
  
  tr:hover {
    background: #f7fafc;
  }
  
  td {
    color: #4a5568;
  }
  
  tr:last-child td {
    border-bottom: none;
  }
`;

const DownloadButton = styled.button`
  background: #4299e1;
  color: white;
  border: none;
  padding: 0.8rem 1.5rem;
  border-radius: 6px;
  font-size: 1rem;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 1rem;
  
  &:hover {
    background: #3182ce;
    transform: translateY(-1px);
  }
  
  &:disabled {
    background: #cbd5e0;
    cursor: not-allowed;
    transform: none;
  }
`;

const LoadingSpinner = styled(FaSpinner)`
  animation: spin 1s linear infinite;
  
  @keyframes spin {
    100% {
      transform: rotate(360deg);
    }
  }
`;

function App() {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [csvData, setCsvData] = useState(null);
  const [success, setSuccess] = useState(false);

  const onDrop = useCallback(async (acceptedFiles) => {
    const file = acceptedFiles[0];
    if (!file) return;

    setFile(file);
    setLoading(true);
    setError(null);
    setSuccess(false);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch('http://localhost:5000/api/upload', {
        method: 'POST',
        body: formData,
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Error processing file');
      }

      setCsvData(data.csvData);
      setSuccess(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf']
    },
    multiple: false
  });

  const handleDownload = () => {
    if (!csvData) return;
    
    const blob = new Blob([csvData], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'output.csv';
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
  };

  const renderCSVData = () => {
    if (!csvData) return null;

    const rows = csvData.split('\n').map(row => row.split(','));
    const headers = rows[0];
    const data = rows.slice(1);

    return (
      <>
        <Table>
          <thead>
            <tr>
              {headers.map((header, index) => (
                <th key={index}>{header}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </Table>
        <DownloadButton onClick={handleDownload}>
          Download CSV
        </DownloadButton>
      </>
    );
  };

  return (
    <AppContainer>
      <Header>
        <Title>EHR Segmenter</Title>
        <Subtitle>
          Upload your PDF file to process and analyze Electronic Health Records.
          Our advanced segmentation tool will help you organize and understand your medical documents.
        </Subtitle>
      </Header>

      <UploadContainer>
        <div {...getRootProps()}>
          <input {...getInputProps()} />
          <Dropzone isDragActive={isDragActive}>
            <UploadIcon />
            <UploadText>
              {isDragActive
                ? "Drop your PDF file here"
                : "Drag and drop your PDF file here, or click to select"}
            </UploadText>
            {file && (
              <UploadText style={{ color: '#4299e1' }}>
                Selected file: {file.name}
              </UploadText>
            )}
          </Dropzone>
        </div>

        {error && (
          <StatusMessage error>
            <FaTimes />
            {error}
          </StatusMessage>
        )}

        {loading && (
          <StatusMessage>
            <LoadingSpinner />
            Processing your file...
          </StatusMessage>
        )}

        {success && (
          <StatusMessage success>
            <FaCheck />
            File processed successfully!
          </StatusMessage>
        )}
      </UploadContainer>

      {csvData && (
        <CSVContainer>
          {renderCSVData()}
        </CSVContainer>
      )}
    </AppContainer>
  );
}

export default App; 