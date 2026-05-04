import React, { useState, useEffect } from 'react';
import { PluggyConnect } from 'react-pluggy-connect';
import { getFunctions, httpsCallable } from 'firebase/functions';
import { getApp } from 'firebase/app';
import { Loader2, Link2, CheckCircle, AlertTriangle, Trash2, RefreshCw, ExternalLink } from 'lucide-react';
import { format } from 'date-fns';
import { ptBR } from 'date-fns/locale';

const BankSyncWidget = ({ user }) => {
    const [connectToken, setConnectToken] = useState(null);
    const [isLoadingIndicator, setIsLoadingIndicator] = useState(false);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [connections, setConnections] = useState([]);
    const [error, setError] = useState(null);
    const [successMessage, setSuccessMessage] = useState(null);
    const [isWidgetVisible, setIsWidgetVisible] = useState(false);

    // Initial Firebase Functions
    const app = getApp();
    const functions = getFunctions(app);

    useEffect(() => {
        if (user) {
            fetchConnections();
        }
    }, [user]);

    const fetchConnections = async () => {
        setIsRefreshing(true);
        try {
            const listUserConnections = httpsCallable(functions, 'listUserConnections');
            const result = await listUserConnections({});
            if (result.data && result.data.connections) {
                setConnections(result.data.connections);
            }
        } catch (err) {
            console.error("Error fetching connections:", err);
            // Non-blocking error for initial load
        } finally {
            setIsRefreshing(false);
        }
    };

    const handleDeleteConnection = async (itemId) => {
        if (!window.confirm("Tem certeza que deseja remover esta conexão bancária? Novas transações não serão mais importadas.")) return;

        setIsRefreshing(true);
        setError(null);
        try {
            const deleteConnection = httpsCallable(functions, 'deleteConnection');
            await deleteConnection({ itemId });
            setSuccessMessage("Conexão removida com sucesso.");
            await fetchConnections();
        } catch (err) {
            console.error("Error deleting connection:", err);
            setError("Não foi possível remover a conexão: " + err.message);
        } finally {
            setIsRefreshing(false);
        }
    };

    const handleConnectBank = async () => {
        setIsLoadingIndicator(true);
        setError(null);
        setSuccessMessage(null);
        try {
            // Call the cloud function to create a connect token
            const createConnectToken = httpsCallable(functions, 'createConnectToken');
            const result = await createConnectToken({});

            if (result.data && result.data.accessToken) {
                setConnectToken(result.data.accessToken);
                setIsWidgetVisible(true);
            } else {
                throw new Error("Invalid token received from server");
            }
        } catch (err) {
            console.error("Error starting bank connection:", err);
            setError("Não foi possível iniciar a conexão com o banco. " + err.message);
        } finally {
            setIsLoadingIndicator(false);
        }
    };

    const handleOnSuccess = async (itemData) => {
        setIsWidgetVisible(false);
        setIsLoadingIndicator(true);
        try {
            // itemData returned by Pluggy contains item.id
            const itemId = itemData?.item?.id || itemData?.id;

            if (!itemId) {
                throw new Error("Item ID not found after successful connection");
            }

            // Call backend to store connection ID
            const exchangeToken = httpsCallable(functions, 'exchangeToken');
            await exchangeToken({ itemId });

            setSuccessMessage("Conta vinculada com sucesso! As transações começarão a sincronizar.");
            await fetchConnections(); // Refresh the list
        } catch (err) {
            console.error("Error exchanging token:", err);
            setError("Conexão autorizada, mas houve um erro ao registrar na sua conta.");
        } finally {
            setIsLoadingIndicator(false);
        }
    };

    const handleOnError = (errorData) => {
        setIsWidgetVisible(false);
        console.error("Pluggy Widget error:", errorData);
        if (errorData?.message !== "User closed the popup") { // avoid error on simple close
            setError("Erro ao conectar no banco: " + (errorData.message || "Desconhecido"));
        }
    };

    const handleOnClose = () => {
        setIsWidgetVisible(false);
    };

    return (
        <div className="bg-slate-800 dark:bg-white p-6 rounded-xl shadow-lg mt-6">
            <div className="flex items-center space-x-2 mb-4">
                <Link2 className="text-cyan-400 dark:text-cyan-700" size={24} />
                <h3 className="text-xl font-semibold text-cyan-400 dark:text-cyan-700">Conexões Bancárias</h3>
            </div>

            <p className="text-sm text-slate-400 dark:text-gray-500 mb-6">
                Vincule suas contas bancárias e cartões para sincronizar transações automaticamente via Open Finance.
                Seguro e integrado.
            </p>

            {error && (
                <div className="bg-red-500/20 text-red-400 p-3 rounded-lg mb-4 text-sm flex items-start">
                    <AlertTriangle size={16} className="mr-2 mt-0.5" /> {error}
                </div>
            )}

            {successMessage && (
                <div className="bg-green-500/20 text-green-400 p-3 rounded-lg mb-4 text-sm flex items-start animate-fade-in">
                    <CheckCircle size={16} className="mr-2 mt-0.5" /> {successMessage}
                </div>
            )}

            {/* Lista de Conexões Atuais */}
            {connections.length > 0 && (
                <div className="mb-6 space-y-3">
                    <div className="flex justify-between items-center mb-2">
                        <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500">Bancos Conectados</h4>
                        <button onClick={fetchConnections} disabled={isRefreshing} className="p-1 hover:bg-slate-700 rounded-full transition-colors">
                            <RefreshCw size={14} className={`${isRefreshing ? 'animate-spin' : ''} text-slate-400`} />
                        </button>
                    </div>
                    {connections.map((conn) => (
                        <div key={conn.id} className="flex items-center justify-between p-3 bg-slate-900/40 border border-slate-700/50 rounded-lg group">
                            <div className="flex items-center space-x-3">
                                {conn.institutionImageUrl && (
                                    <img src={conn.institutionImageUrl} alt={conn.institution} className="h-8 w-8 rounded bg-white p-0.5" />
                                )}
                                <div>
                                    <p className="font-medium text-slate-200 text-sm">{conn.institution}</p>
                                    <p className="text-[10px] text-slate-500">
                                        Sincronizado em: {conn.updatedAt && !isNaN(new Date(conn.updatedAt).getTime())
                                            ? format(new Date(conn.updatedAt), "dd/MM 'às' HH:mm", { locale: ptBR })
                                            : 'Pendente'}
                                    </p>
                                </div>
                            </div>
                            <div className="flex space-x-1">
                                <span className={`h-2 w-2 rounded-full mt-2 mr-2 ${conn.status === 'UPDATED' ? 'bg-green-500' : 'bg-yellow-500'} animate-pulse`} />
                                <button
                                    onClick={() => handleDeleteConnection(conn.id)}
                                    className="p-2 text-slate-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-all"
                                    title="Remover conexão"
                                >
                                    <Trash2 size={16} />
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {!isWidgetVisible ? (
                <button
                    onClick={handleConnectBank}
                    disabled={isLoadingIndicator || isRefreshing}
                    className="w-full bg-cyan-600 hover:bg-cyan-500 disabled:bg-cyan-800 disabled:opacity-50 text-white font-semibold py-3 px-4 rounded-lg flex items-center justify-center transition-all group"
                >
                    {isLoadingIndicator ? (
                        <><Loader2 size={18} className="mr-2 animate-spin" /> Iniciando...</>
                    ) : (
                        <><PluggyIcon className="mr-2 h-5 w-5 group-hover:scale-110 transition-transform" /> Conectar Novo Banco</>
                    )}
                </button>
            ) : (
                <div className="text-center p-8 border-2 border-dashed border-cyan-800/30 rounded-xl bg-slate-900/50">
                    <Loader2 size={32} className="mx-auto mb-4 animate-spin text-cyan-500 opacity-50" />
                    <p className="text-sm text-slate-400">Aguardando autorização segura na janela pop-up...</p>
                </div>
            )}

            {isWidgetVisible && connectToken && (
                <PluggyConnect
                    connectToken={connectToken}
                    includeSandbox={true}
                    onSuccess={handleOnSuccess}
                    onError={handleOnError}
                    onClose={handleOnClose}
                />
            )}
        </div>
    );
};

// SVG Icon Helper
const PluggyIcon = ({ className }) => (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 12V7H5a2 2 0 0 1 0-4h14v4" />
        <path d="M3 5v14a2 2 0 0 0 2 2h16v-5" />
        <path d="M18 12a2 2 0 0 0 0 4h4v-4Z" />
    </svg>
);

export default BankSyncWidget;
