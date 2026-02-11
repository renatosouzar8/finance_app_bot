import React, { useState, useEffect, useMemo, useCallback } from 'react';
import FinancialEvolutionChart from './components/FinancialEvolutionChart';
import FinancialCategoryChart from './components/FinancialCategoryChart';
import { initializeApp } from 'firebase/app';
import {
    getAuth,
    signInWithEmailAndPassword,
    createUserWithEmailAndPassword,
    signOut,
    onAuthStateChanged,
    signInAnonymously,
    signInWithCustomToken
} from 'firebase/auth';
import {
    getFirestore,
    collection,
    addDoc,
    query,
    where,
    onSnapshot,
    doc,
    setDoc,
    updateDoc,
    deleteDoc,
    Timestamp,
    orderBy,
    getDocs,
    documentId
} from 'firebase/firestore';
import { ChevronDown, ChevronUp, PlusCircle, Edit3, Trash2, Copy, Search, Filter, XCircle, CheckCircle, CalendarDays, TrendingUp, PieChart as IconPieChart, Target, LogOut, Moon, Sun, Settings, Eye, EyeOff, Zap, AlertTriangle, MessageSquareText, ChevronLeft, ChevronRight, Sigma, Loader2, Send } from 'lucide-react'; // Adicionado Send para Telegram
import { AreaChart, Area, BarChart, Bar, LineChart, Line, PieChart as RechartsPieChart, Pie, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell } from 'recharts';
import { format, startOfMonth, endOfMonth, addMonths, subMonths, getMonth, getYear, eachDayOfInterval, parseISO, isValid, isSameMonth, isSameDay, differenceInCalendarMonths } from 'date-fns';
import { ptBR } from 'date-fns/locale';

// Variáveis globais do ambiente
const appId = typeof __app_id !== 'undefined' ? __app_id : 'default-app-id';
const firebaseConfig = {
    apiKey: "AIzaSyCdhoyz5cnmKXdGTEsD3dED-ABtLZUwWuw",
    authDomain: "my-finance-app-24d0f.firebaseapp.com",
    projectId: "my-finance-app-24d0f",
    storageBucket: "my-finance-app-24d0f.firebasestorage.app",
    messagingSenderId: "122828550275",
    appId: "1:122828550275:web:02ad3855ed54fb43b82bb6"
};
const initialAuthToken = typeof __initial_auth_token !== 'undefined' ? __initial_auth_token : undefined;

// Inicialização do Firebase
const firebaseApp = initializeApp(firebaseConfig);
const auth = getAuth(firebaseApp);
const db = getFirestore(firebaseApp);

// Constantes
const TRANSACTION_TYPES = { INCOME: 'income', EXPENSE: 'expense' };
const CATEGORIES = {
    INCOME: ['Salário', 'Freelance', 'Investimentos', 'Rendimentos', 'Vendas', 'Outros'],
    EXPENSE: ['Moradia', 'Alimentação', 'Transporte', 'Lazer', 'Saúde', 'Educação', 'Compras', 'Impostos', 'Serviços', 'Dívidas', 'Outros']
};
const COLORS = ['#6366f1', '#10b981', '#f59e0b', '#ec4899', '#8b5cf6', '#06b6d4', '#f43f5e', '#84cc16', '#a855f7', '#14b8a6', '#f97316', '#3b82f6'];

// Constantes da API Gemini
const GEMINI_API_KEY = "AIzaSyBb7DECg0rhiSg1C4adRwmT-Nu3Czhvn5U";
const GEMINI_API_URL = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${GEMINI_API_KEY}`;

// Função auxiliar para chamar a API Gemini
const callGeminiAPI = async (prompt) => {
    console.log("Enviando prompt para Gemini:", prompt);
    if (!GEMINI_API_KEY) {
        throw new Error("GEMINI_API_KEY não está configurada.");
    }
    try {
        const payload = {
            contents: [{ role: "user", parts: [{ text: prompt }] }]
        };
        const response = await fetch(GEMINI_API_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!response.ok) {
            const errorData = await response.json();
            console.error("Erro na API Gemini (resposta não OK):", response.status, errorData);
            throw new Error(`Erro na API Gemini: ${response.statusText} - ${JSON.stringify(errorData)}`);
        }
        const result = await response.json();
        console.log("Resposta completa da Gemini:", JSON.stringify(result, null, 2));

        if (result.candidates && result.candidates.length > 0 &&
            result.candidates[0].content && result.candidates[0].content.parts &&
            result.candidates[0].content.parts.length > 0) {
            const textResponse = result.candidates[0].content.parts[0].text.trim();
            console.log("Texto extraído da Gemini:", textResponse);
            return textResponse;
        } else {
            console.warn("Resposta inesperada ou vazia da API Gemini:", result);
            if (result.promptFeedback && result.promptFeedback.blockReason) {
                console.error("Prompt bloqueado pela API Gemini:", result.promptFeedback.blockReason, result.promptFeedback.safetyRatings);
                throw new Error(`Prompt bloqueado: ${result.promptFeedback.blockReason}`);
            }
            return null;
        }
    } catch (error) {
        console.error("Falha ao chamar a API Gemini (catch):", error);
        throw error;
    }
};

const DatePicker = ({ selectedDate, onChange, id }) => {
    const [inputValue, setInputValue] = useState(selectedDate ? format(selectedDate, 'yyyy-MM-dd') : '');
    useEffect(() => {
        setInputValue(selectedDate ? format(selectedDate, 'yyyy-MM-dd') : '');
    }, [selectedDate]);
    const handleInputChange = (e) => {
        const newDate = parseISO(e.target.value);
        setInputValue(e.target.value);
        if (isValid(newDate)) { onChange(newDate); }
        else if (e.target.value === '') { onChange(null); }
    };
    return <input id={id} type="date" value={inputValue} onChange={handleInputChange} className="w-full p-3 bg-slate-700 border border-slate-600 rounded-lg text-slate-100 focus:ring-2 focus:ring-cyan-500 focus:border-cyan-500 transition-colors dark:bg-gray-200 dark:border-gray-300 dark:text-slate-900" />;
};

const Modal = ({ isOpen, onClose, title, children }) => {
    if (!isOpen) return null;
    return (
        <div className="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50 p-4">
            <div className="bg-slate-800 dark:bg-white p-6 rounded-xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
                <div className="flex justify-between items-center mb-6">
                    <h3 className="text-2xl font-semibold text-cyan-400 dark:text-cyan-700">{title}</h3>
                    <button onClick={onClose} className="text-slate-400 hover:text-red-500 dark:text-gray-500 dark:hover:text-red-600 transition-colors"><XCircle size={28} /></button>
                </div>
                {children}
            </div>
        </div>
    );
};

const AuthComponent = ({ setUser }) => {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [isLogin, setIsLogin] = useState(true);
    const [error, setError] = useState('');
    const [showPassword, setShowPassword] = useState(false);
    const handleAuth = async (e) => {
        e.preventDefault(); setError('');
        try {
            if (isLogin) { await signInWithEmailAndPassword(auth, email, password); }
            else { await createUserWithEmailAndPassword(auth, email, password); }
        } catch (err) { console.error("Erro de autenticação:", err); setError(err.message || 'Falha na autenticação.'); }
    };
    return (
        <div className="min-h-screen flex flex-col items-center justify-center bg-slate-900 dark:bg-gray-100 p-4">
            <div className="w-full max-w-md bg-slate-800 dark:bg-white p-8 rounded-xl shadow-2xl">
                <h2 className="text-4xl font-bold text-center text-cyan-400 dark:text-cyan-700 mb-8">{isLogin ? 'Login' : 'Criar Conta'}</h2>
                {error && <p className="bg-red-500/20 text-red-400 p-3 rounded-lg mb-6 text-sm">{error}</p>}
                <form onSubmit={handleAuth} className="space-y-6">
                    <div><label htmlFor="email-auth" className="block text-sm font-medium text-slate-300 dark:text-slate-700 mb-1">Email</label><input type="email" id="email-auth" value={email} onChange={(e) => setEmail(e.target.value)} required className="w-full p-3 bg-slate-700 border border-slate-600 rounded-lg text-slate-100 focus:ring-2 focus:ring-cyan-500 dark:bg-gray-200 dark:border-gray-300 dark:text-slate-900" placeholder="seu@email.com" /></div>
                    <div><label htmlFor="password-auth" className="block text-sm font-medium text-slate-300 dark:text-slate-700 mb-1">Senha</label><div className="relative"><input type={showPassword ? "text" : "password"} id="password-auth" value={password} onChange={(e) => setPassword(e.target.value)} required className="w-full p-3 bg-slate-700 border border-slate-600 rounded-lg text-slate-100 focus:ring-2 focus:ring-cyan-500 dark:bg-gray-200 dark:border-gray-300 dark:text-slate-900" placeholder="Sua senha" /><button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute inset-y-0 right-0 px-3 flex items-center text-slate-400 hover:text-cyan-400 dark:text-gray-500 dark:hover:text-cyan-700">{showPassword ? <EyeOff size={20} /> : <Eye size={20} />}</button></div></div>
                    <button type="submit" className="w-full bg-cyan-600 hover:bg-cyan-500 text-white font-semibold p-3 rounded-lg transition-colors transform hover:scale-105 dark:bg-cyan-700 dark:hover:bg-cyan-600">{isLogin ? 'Entrar' : 'Registrar'}</button>
                </form>
                <button onClick={() => { setIsLogin(!isLogin); setError(''); }} className="mt-6 text-sm text-cyan-400 hover:text-cyan-300 dark:text-cyan-700 dark:hover:text-cyan-600 w-full text-center">{isLogin ? 'Não tem uma conta? Crie uma agora!' : 'Já tem uma conta? Faça login!'}</button>
                <p className="mt-2 text-xs text-slate-500 dark:text-gray-400 text-center">User ID: {auth.currentUser?.uid || "N/A"}</p>
            </div>
        </div>
    );
};

const TransactionForm = ({ isOpen, onClose, onSave, editingTransaction, currentMonth }) => {
    const [description, setDescription] = useState('');
    const [amount, setAmount] = useState('');
    const [date, setDate] = useState(new Date());
    const [type, setType] = useState(TRANSACTION_TYPES.EXPENSE);
    const [category, setCategory] = useState('');
    const [isInstallment, setIsInstallment] = useState(false);
    const [numberOfInstallments, setNumberOfInstallments] = useState(10);
    const [isSuggestingCategory, setIsSuggestingCategory] = useState(false);
    const [suggestionError, setSuggestionError] = useState('');
    const [formError, setFormError] = useState('');

    const isEditing = !!editingTransaction;
    const isEditingInstallment = isEditing && (editingTransaction.isInstallmentOriginal || editingTransaction.isInstallmentPayment);

    useEffect(() => {
        if (editingTransaction) {
            setDescription(editingTransaction.description || '');
            setAmount(editingTransaction.isInstallmentOriginal ? (editingTransaction.valuePerInstallment?.toString() || '') : (editingTransaction.amount?.toString() || ''));
            const transactionDate = editingTransaction.date?.toDate ? editingTransaction.date.toDate() : (editingTransaction.date ? new Date(editingTransaction.date) : startOfMonth(currentMonth || new Date()));
            setDate(isValid(transactionDate) ? transactionDate : startOfMonth(currentMonth || new Date()));
            setType(editingTransaction.type || TRANSACTION_TYPES.EXPENSE);
            setCategory(editingTransaction.category || '');
            setIsInstallment(editingTransaction.isInstallmentOriginal || false);
            if (editingTransaction.isInstallmentOriginal) {
                setNumberOfInstallments(editingTransaction.numberOfInstallments || 10);
            }
        } else {
            setDescription(''); setAmount('');
            setDate(currentMonth ? startOfMonth(currentMonth) : new Date());
            setType(TRANSACTION_TYPES.EXPENSE); setCategory('');
            setIsInstallment(false); setNumberOfInstallments(10);
        }
        setSuggestionError(''); setFormError('');
    }, [editingTransaction, isOpen, currentMonth]);

    const handleSuggestCategory = async () => {
        if (!description) { setSuggestionError("Insira uma descrição."); return; }
        if (!GEMINI_API_KEY) { setSuggestionError("Chave da API Gemini não configurada."); return; }

        setIsSuggestingCategory(true); setSuggestionError(''); setFormError('');
        try {
            const relevantCategories = type === TRANSACTION_TYPES.EXPENSE ? CATEGORIES.EXPENSE : CATEGORIES.INCOME;
            const prompt = `Descrição da transação: "${description}". Categorias de ${type === TRANSACTION_TYPES.EXPENSE ? 'Despesa' : 'Receita'}: ${relevantCategories.join(', ')}. Qual categoria da lista é mais apropriada? Responda APENAS o nome da categoria. Se nenhuma, 'Outros'.`;
            const suggested = await callGeminiAPI(prompt);
            if (suggested && relevantCategories.includes(suggested)) { setCategory(suggested); }
            else if (suggested) {
                const matchedCategory = relevantCategories.find(c => c.toLowerCase() === suggested.toLowerCase());
                if (matchedCategory) { setCategory(matchedCategory); }
                else { setCategory('Outros'); setSuggestionError(`Sugestão "${suggested}" inválida. Usando 'Outros'.`); }
            } else { setSuggestionError("Não foi possível sugerir."); setCategory('Outros'); }
        } catch (error) { setSuggestionError(`Falha: ${error.message}.`); setCategory('Outros'); }
        finally { setIsSuggestingCategory(false); }
    };

    const handleSubmit = (e) => {
        e.preventDefault(); setFormError('');
        if (!description || !amount || !date || !type || !category) { setFormError("Preencha todos os campos."); return; }
        const numericAmount = parseFloat(amount);
        if (isNaN(numericAmount) || numericAmount <= 0) { setFormError("Valor da parcela/transação deve ser positivo."); return; }
        if (!isValid(date)) { setFormError("Data inválida."); return; }

        // Bloqueia edição de tipo e parcelamento para pagamentos de parcela
        if (isEditingInstallment && editingTransaction.isInstallmentPayment) {
            if (type !== editingTransaction.type) { setFormError("Não é permitido alterar o tipo de um pagamento de parcela."); return; }
        }

        const transactionData = {
            description,
            amount: numericAmount,
            date: Timestamp.fromDate(date),
            type,
            category,
            isInstallment
        };

        if (isInstallment && !isEditingInstallment) {
            const numInstallments = parseInt(numberOfInstallments, 10);
            if (isNaN(numInstallments) || numInstallments < 2) { setFormError("Número de parcelas deve ser ao menos 2."); return; }
            transactionData.numberOfInstallments = numInstallments;
        } else if (isEditingInstallment && editingTransaction.isInstallmentOriginal) {
            // Permite editar número de parcelas na mãe
            const numInstallments = parseInt(numberOfInstallments, 10);
            if (isNaN(numInstallments) || numInstallments < 2) { setFormError("Número de parcelas deve ser ao menos 2."); return; }
            transactionData.numberOfInstallments = numInstallments;
        }

        onSave(transactionData, editingTransaction ? editingTransaction.id : null);
        onClose();
    };

    const categoriesToShow = type === TRANSACTION_TYPES.INCOME ? CATEGORIES.INCOME : CATEGORIES.EXPENSE;

    // Desabilita campos chave na edição de parcelamentos para evitar complexidade
    const isTypeDisabled = isEditingInstallment;
    const isAmountDisabled = isEditingInstallment;
    const isDateDisabled = isEditingInstallment;
    const isInstallmentCheckboxDisabled = isEditingInstallment;
    const isNumInstallmentsDisabled = isEditingInstallment && editingTransaction.isInstallmentPayment;

    return (
        <Modal isOpen={isOpen} onClose={onClose} title={editingTransaction ? "Editar Transação" : "Adicionar Transação"}>
            <form onSubmit={handleSubmit} className="space-y-4">
                {formError && <p className="bg-red-500/20 text-red-400 p-3 rounded-lg text-sm">{formError}</p>}
                {isEditingInstallment && <p className="bg-yellow-500/20 text-yellow-400 p-3 rounded-lg text-sm flex items-center"><AlertTriangle size={18} className="mr-2" /> Não é possível alterar Tipo, Valor, Data ou Parcelamento para esta transação.</p>}

                <div><label htmlFor="description-form" className="block text-sm font-medium text-slate-300 dark:text-slate-700">Descrição</label><input id="description-form" type="text" value={description} onChange={(e) => setDescription(e.target.value)} required className="mt-1 w-full p-3 bg-slate-700 rounded-lg dark:bg-gray-200 dark:text-slate-900" /></div>

                <div><label htmlFor="amount-form" className="block text-sm font-medium text-slate-300 dark:text-slate-700">{isInstallment ? "Valor da Parcela (R$)" : "Valor (R$)"}</label><input id="amount-form" type="number" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} required className="mt-1 w-full p-3 bg-slate-700 rounded-lg dark:bg-gray-200 dark:text-slate-900 disabled:opacity-70" disabled={isAmountDisabled} /></div>

                <div><label htmlFor="date-transaction-form" className="block text-sm font-medium text-slate-300 dark:text-slate-700">Data {isInstallment ? "da 1ª Parcela/Compra" : ""}</label><DatePicker id="date-transaction-form" selectedDate={date} onChange={setDate} disabled={isDateDisabled} /></div>

                <div><label htmlFor="type-transaction-form" className="block text-sm font-medium text-slate-300 dark:text-slate-700">Tipo</label><select id="type-transaction-form" value={type} onChange={(e) => { setType(e.target.value); setCategory(''); setSuggestionError(''); }} required className="mt-1 w-full p-3 bg-slate-700 rounded-lg dark:bg-gray-200 dark:text-slate-900 disabled:opacity-70" disabled={isTypeDisabled}><option value={TRANSACTION_TYPES.EXPENSE}>Despesa</option><option value={TRANSACTION_TYPES.INCOME}>Receita</option></select></div>

                <div>
                    <div className="flex justify-between items-center">
                        <label htmlFor="category-transaction-form" className="block text-sm font-medium text-slate-300 dark:text-slate-700">Categoria</label>
                        <button type="button" onClick={handleSuggestCategory} disabled={isSuggestingCategory || !description || !GEMINI_API_KEY} className="text-xs bg-teal-600 hover:bg-teal-500 text-white font-semibold py-1 px-2 rounded-md flex items-center disabled:opacity-50">
                            {isSuggestingCategory ? (<><Loader2 size={14} className="mr-1 animate-spin" /> Sugerindo...</>) : (<><Zap size={14} className="mr-1" /> ✨ Sugerir</>)}
                        </button>
                    </div>
                    <select id="category-transaction-form" value={category} onChange={(e) => setCategory(e.target.value)} required className="mt-1 w-full p-3 bg-slate-700 rounded-lg dark:bg-gray-200 dark:text-slate-900"><option value="">Selecione</option>{categoriesToShow.map(cat => <option key={cat} value={cat}>{cat}</option>)}</select>{suggestionError && <p className="text-red-400 text-xs mt-1">{suggestionError}</p>}
                </div>

                <div className="flex items-center space-x-3">
                    <input type="checkbox" id="isInstallment-form" checked={isInstallment} onChange={(e) => setIsInstallment(e.target.checked)} className="h-5 w-5 text-cyan-600 rounded dark:text-cyan-700 disabled:opacity-50" disabled={isInstallmentCheckboxDisabled} />
                    <label htmlFor="isInstallment-form" className={`text-sm text-slate-300 dark:text-slate-700 ${isInstallmentCheckboxDisabled ? 'opacity-70' : ''}`}>Compra Parcelada?</label>
                </div>

                {isInstallment && (
                    <div>
                        <label htmlFor="numberOfInstallments-form" className="block text-sm font-medium text-slate-300 dark:text-slate-700">Número de Parcelas</label>
                        <input id="numberOfInstallments-form" type="number" min="2" value={numberOfInstallments} onChange={(e) => setNumberOfInstallments(e.target.value)} required className="mt-1 w-full p-3 bg-slate-700 rounded-lg dark:bg-gray-200 dark:text-slate-900 disabled:opacity-70" disabled={isNumInstallmentsDisabled} />
                    </div>
                )}

                <div className="flex justify-end space-x-3 pt-4">
                    <button type="button" onClick={onClose} className="px-6 py-3 bg-slate-600 hover:bg-slate-500 rounded-lg dark:bg-gray-300 dark:hover:bg-gray-400 dark:text-slate-900">Cancelar</button>
                    <button type="submit" className="px-6 py-3 bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg dark:bg-cyan-700 dark:hover:bg-cyan-600">Salvar</button>
                </div>
            </form>
        </Modal>
    );
};

const TransactionItem = ({ transaction, onEdit, onDelete, onTogglePaid }) => {
    const { description, amount, date, type, category, id, isPaid: transactionIsPaid, isInstallmentPayment, isInstallmentOriginal } = transaction;
    const transactionDateObj = date?.toDate ? date.toDate() : (date ? new Date(date) : null);
    const formattedDate = transactionDateObj && isValid(transactionDateObj) ? format(transactionDateObj, 'dd/MM/yyyy', { locale: ptBR }) : 'Data inválida';
    const isExpense = type === TRANSACTION_TYPES.EXPENSE;
    const isEditable = !isInstallmentPayment;

    return (
        <div className="p-4 rounded-lg shadow-md transition-all bg-slate-700/50 hover:bg-slate-700 dark:bg-white dark:hover:bg-gray-100">
            <div className="flex items-start justify-between">
                <div className="flex items-center space-x-3">
                    <div>
                        <h4 className="text-lg font-semibold text-slate-100 dark:text-slate-800">{description}</h4>
                        <p className="text-xs text-slate-400 dark:text-gray-500">{category || 'Sem categoria'} - {formattedDate}</p>
                    </div>
                </div>
                <div className="text-right">
                    <p className={`text-xl font-bold ${isExpense ? 'text-red-400 dark:text-red-600' : 'text-green-400 dark:text-green-600'}`}>{isExpense ? '-' : '+'} R$ {amount ? amount.toFixed(2) : '0.00'}</p>
                    {isInstallmentPayment && (
                        <button onClick={() => onTogglePaid(transaction.id, !transactionIsPaid)} className={`mt-1 text-xs px-2 py-1 rounded ${transactionIsPaid ? 'bg-green-500/80 hover:bg-green-500 text-slate-900' : 'bg-yellow-500/80 hover:bg-yellow-500 text-slate-900'}`}>{transactionIsPaid ? <CheckCircle size={14} className="inline mr-1" /> : <XCircle size={14} className="inline mr-1" />}{transactionIsPaid ? 'Pago' : 'Pendente'}</button>
                    )}
                </div>
            </div>
            <div className="mt-3 flex items-center justify-end space-x-2">
                {isEditable && <button onClick={() => onEdit(transaction)} className="p-2 text-slate-400 hover:text-yellow-400 dark:text-gray-500 dark:hover:text-yellow-600"><Edit3 size={18} /></button>}
                <button onClick={() => onDelete(transaction)} className="p-2 text-slate-400 hover:text-red-400 dark:text-gray-500 dark:hover:text-red-600"><Trash2 size={18} /></button>
            </div>
        </div>
    );
};

const InstallmentsReport = ({ userId, onEdit, onDelete, showAll = false }) => {
    const [installments, setInstallments] = useState([]);
    const [installmentPayments, setInstallmentPayments] = useState([]);
    const [showFinished, setShowFinished] = useState(false);
    const [expandedInstallmentId, setExpandedInstallmentId] = useState(null);
    const [loading, setLoading] = useState(true);
    const [customError, setCustomError] = useState('');
    const installmentsPath = `artifacts/${appId}/users/${userId}/installments`;
    const installmentPaymentsPath = `artifacts/${appId}/users/${userId}/installment_payments`;

    useEffect(() => {
        if (!userId) { setLoading(false); return; }
        setLoading(true);
        const q = query(collection(db, installmentsPath), orderBy("purchaseDate", "desc"));
        const unsubInst = onSnapshot(q, (snap) => { setInstallments(snap.docs.map(d => ({ id: d.id, ...d.data() }))); setLoading(false); },
            (err) => { console.error(err); setCustomError("Falha ao carregar parcelamentos."); setLoading(false); });

        const qPay = query(collection(db, installmentPaymentsPath), orderBy("dueDate", "asc"));
        const unsubPay = onSnapshot(qPay, (snap) => setInstallmentPayments(snap.docs.map(d => ({ id: d.id, ...d.data() }))),
            (err) => { console.error(err); setCustomError("Falha ao carregar pagamentos de parcelas."); });

        return () => { unsubInst(); unsubPay(); };
    }, [userId, installmentsPath, installmentPaymentsPath]);

    const toggleInstallmentDetails = (id) => setExpandedInstallmentId(prev => (prev === id ? null : id));
    const handleTogglePaymentStatus = async (paymentId, newStatus) => {
        if (!userId) return; setCustomError('');
        try { await updateDoc(doc(db, installmentPaymentsPath, paymentId), { isPaid: newStatus, paidDate: newStatus ? Timestamp.now() : null }); }
        catch (error) { console.error(error); setCustomError("Falha ao atualizar status."); }
    };

    if (loading && installments.length === 0) return <div className="text-center p-4 text-slate-400 dark:text-gray-500">Carregando...</div>;
    return (
        <div className="bg-slate-800 dark:bg-white p-6 rounded-xl shadow-lg">
            <div className="flex justify-between items-center mb-6">
                <h3 className="text-2xl font-semibold text-violet-400 dark:text-violet-700">Relatório de Compras Parceladas</h3>
                <div className="flex items-center space-x-2">
                    <label htmlFor="show-finished-toggle" className="text-sm text-slate-400 dark:text-gray-500 cursor-pointer">Mostrar Quitados</label>
                    <button
                        id="show-finished-toggle"
                        onClick={() => setShowFinished(!showFinished)}
                        className={`w-10 h-6 rounded-full p-1 transition-colors ${showFinished ? 'bg-violet-500' : 'bg-slate-600 dark:bg-gray-300'}`}
                    >
                        <div className={`bg-white w-4 h-4 rounded-full shadow-md transform transition-transform ${showFinished ? 'translate-x-4' : ''}`}></div>
                    </button>
                </div>
            </div>
            {customError && <p className="bg-red-500/20 text-red-400 p-3 mb-4 text-sm">{customError}</p>}
            {installments.length === 0 && !loading && <div className="p-4 rounded-lg text-slate-400 dark:text-gray-500 text-center">Nenhuma compra parcelada.</div>}

            {(installments.filter(inst => {
                const relP = installmentPayments.filter(p => p.installmentId === inst.id);
                const paidC = relP.filter(p => p.isPaid).length;
                const totalInstallments = Number(inst.numberOfInstallments) || 0;
                const isFinished = totalInstallments > 0 && paidC >= totalInstallments;
                if (showFinished) return true;
                return !isFinished;
            }).length === 0 && installments.length > 0) && (
                    <div className="p-8 border-2 border-dashed border-slate-700 dark:border-gray-200 rounded-xl text-center">
                        <p className="text-slate-400 dark:text-gray-500 mb-2">🎈 Tudo pago!</p>
                        <p className="text-sm text-slate-500 dark:text-gray-400">Nenhuma compra parcelada pendente.</p>
                    </div>
                )}
            <div className="space-y-4">{installments.filter(inst => {
                const relP = installmentPayments.filter(p => p.installmentId === inst.id);
                const paidC = relP.filter(p => p.isPaid).length;
                const totalInstallments = Number(inst.numberOfInstallments) || 0;
                const isFinished = totalInstallments > 0 && paidC >= totalInstallments;

                if (showFinished) return true;
                return !isFinished;
            }).map(inst => {
                const relP = installmentPayments.filter(p => p.installmentId === inst.id);
                const paidC = relP.filter(p => p.isPaid).length;
                const totalInstallments = Number(inst.numberOfInstallments) || 0;
                const isFinished = totalInstallments > 0 && paidC >= totalInstallments;
                const isExp = expandedInstallmentId === inst.id;
                const pDateObj = inst.purchaseDate?.toDate ? inst.purchaseDate.toDate() : null;
                const fmtPDate = pDateObj && isValid(pDateObj) ? format(pDateObj, 'dd/MM/yyyy', { locale: ptBR }) : 'Inválida';
                return (
                    <div key={inst.id} className={`p-4 rounded-lg border ${isFinished ? 'bg-slate-800/40 border-slate-700/50' : 'bg-slate-700/50 dark:bg-gray-100 border-transparent'}`}>
                        <div className="flex justify-between items-center cursor-pointer" onClick={() => toggleInstallmentDetails(inst.id)}>
                            <div>
                                <div className="flex items-center space-x-2">
                                    <h4 className={`text-lg font-medium ${isFinished ? 'text-slate-300 dark:text-slate-600' : 'text-slate-100 dark:text-slate-800'}`}>{inst.description}</h4>
                                    {isFinished && <span className="bg-green-500/20 text-green-400 text-xs px-2 py-0.5 rounded-full border border-green-500/30">Quitado</span>}
                                </div>
                                <p className={`text-sm ${isFinished ? 'text-slate-400 dark:text-gray-500 font-medium' : 'text-slate-400 dark:text-gray-500'}`}>
                                    Total: <span className={isFinished ? 'text-slate-300 dark:text-gray-600 font-semibold' : ''}>R$ {(inst.totalAmount || 0).toFixed(2)}</span> | Parcelas: {paidC}/{inst.numberOfInstallments || 0}
                                </p>
                                <p className="text-xs text-slate-500 dark:text-gray-600">Compra: {fmtPDate}</p>
                            </div>
                            <div className="flex items-center space-x-2">
                                <button onClick={(e) => { e.stopPropagation(); onEdit({ ...inst, isInstallmentOriginal: true }); }} className="p-2 text-slate-400 hover:text-yellow-400 dark:text-gray-500 dark:hover:text-yellow-600"><Edit3 size={18} /></button>
                                <button onClick={(e) => { e.stopPropagation(); onDelete({ ...inst, isInstallmentOriginal: true }); }} className="p-2 text-slate-400 hover:text-red-400 dark:text-gray-500 dark:hover:text-red-600"><Trash2 size={18} /></button>
                                {isExp ? <ChevronUp size={24} className="text-violet-400 dark:text-violet-700" /> : <ChevronDown size={24} className="text-violet-400 dark:text-violet-700" />}
                            </div>
                        </div>
                        {isExp && (<div className="mt-4 space-y-2 pl-4 border-l-2 border-violet-500 dark:border-violet-700">{relP.length > 0 ? relP.map(p => {
                            const dDateObj = p.dueDate?.toDate ? p.dueDate.toDate() : null;
                            const fmtDDate = dDateObj && isValid(dDateObj) ? format(dDateObj, 'dd/MM/yyyy', { locale: ptBR }) : 'Inválida';
                            return (<div key={p.id} className="flex justify-between items-center p-2 bg-slate-600/50 dark:bg-gray-200/50 rounded"><div><p className="text-sm text-slate-200 dark:text-slate-800">Parcela {p.paymentNumber}: R$ {(p.amount || 0).toFixed(2)}</p><p className="text-xs text-slate-400 dark:text-gray-500">Venc.: {fmtDDate}</p></div><button onClick={() => handleTogglePaymentStatus(p.id, !p.isPaid)} className={`px-3 py-1 rounded text-xs flex items-center ${p.isPaid ? 'bg-green-500/80' : 'bg-yellow-500/80 text-slate-900'}`}>{p.isPaid ? <CheckCircle size={16} className="mr-1" /> : <XCircle size={16} className="mr-1" />}{p.isPaid ? 'Pago' : 'Pendente'}</button></div>);
                        }) : <p className="text-sm text-slate-400 dark:text-gray-500">Sem detalhes.</p>}</div>)}
                    </div>);
            })}</div>
        </div>
    );
};

const GoalsSection = ({ userId }) => {
    const [goals, setGoals] = useState([]);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [goalName, setGoalName] = useState('');
    const [goalTargetAmount, setGoalTargetAmount] = useState('');
    const [goalCurrentAmount, setGoalCurrentAmount] = useState('');
    const [editingGoal, setEditingGoal] = useState(null);
    const [customError, setCustomError] = useState('');
    const goalsPath = `artifacts/${appId}/users/${userId}/goals`;

    useEffect(() => {
        if (!userId) return;
        const q = query(collection(db, goalsPath), orderBy("createdAt", "desc"));
        const unsub = onSnapshot(q, (snap) => setGoals(snap.docs.map(d => ({ id: d.id, ...d.data() }))),
            (err) => { console.error(err); setCustomError("Falha ao carregar metas."); });
        return () => unsub();
    }, [userId, goalsPath]);

    const handleSaveGoal = async () => {
        setCustomError('');
        if (!goalName || !goalTargetAmount) { setCustomError("Nome e valor alvo são obrigatórios."); return; }
        const targetAmountNum = parseFloat(goalTargetAmount);
        const currentAmountNum = parseFloat(goalCurrentAmount || 0);

        if (isNaN(targetAmountNum) || targetAmountNum <= 0) { setCustomError("Valor alvo deve ser positivo."); return; }
        if (isNaN(currentAmountNum) || currentAmountNum < 0) { setCustomError("Valor atual deve ser positivo ou zero."); return; }
        if (currentAmountNum > targetAmountNum) { setCustomError("Valor atual não pode ser maior que o valor alvo."); return; }

        try {
            const goalData = {
                name: goalName,
                targetAmount: targetAmountNum,
                currentAmount: currentAmountNum
            };

            if (editingGoal) {
                await updateDoc(doc(db, goalsPath, editingGoal.id), goalData);
            } else {
                await addDoc(collection(db, goalsPath), { ...goalData, createdAt: Timestamp.now(), userId });
            }
            setGoalName(''); setGoalTargetAmount(''); setGoalCurrentAmount('');
            setEditingGoal(null); setIsModalOpen(false);
        } catch (err) { console.error(err); setCustomError("Falha ao salvar meta."); }
    };

    const openEditModal = (g) => {
        setEditingGoal(g);
        setGoalName(g.name);
        setGoalTargetAmount(g.targetAmount.toString());
        setGoalCurrentAmount((g.currentAmount || 0).toString());
        setCustomError('');
        setIsModalOpen(true);
    };

    const handleDeleteGoal = async (id) => { if (window.confirm("Excluir esta meta?")) { setCustomError(''); try { await deleteDoc(doc(db, goalsPath, id)); } catch (err) { setCustomError("Falha ao excluir."); } } };

    const openAddModal = () => {
        setEditingGoal(null);
        setGoalName('');
        setGoalTargetAmount('');
        setGoalCurrentAmount('0');
        setCustomError('');
        setIsModalOpen(true);
    };

    return (
        <div className="bg-slate-800 dark:bg-white p-6 rounded-xl shadow-lg">
            <div className="flex justify-between items-center mb-6"><h3 className="text-2xl font-semibold text-emerald-400 dark:text-emerald-700">Metas Financeiras</h3><button onClick={openAddModal} className="bg-emerald-600 hover:bg-emerald-500 dark:bg-emerald-700 dark:hover:bg-emerald-600 text-white font-semibold py-2 px-4 rounded-lg flex items-center"><PlusCircle size={20} className="mr-2" /> Nova Meta</button></div>
            {customError && <p className="bg-red-500/20 text-red-400 p-3 mb-4 text-sm">{customError}</p>}
            {goals.length === 0 && <p className="text-slate-400 dark:text-gray-500 text-center">Nenhuma meta cadastrada.</p>}
            <div className="space-y-4">{goals.map(g => {
                const prog = g.targetAmount > 0 ? ((g.currentAmount || 0) / g.targetAmount) * 100 : 0;
                return (<div key={g.id} className="bg-slate-700/50 dark:bg-gray-100 p-4 rounded-lg"><div className="flex justify-between items-start"><div><h4 className="text-lg font-medium text-slate-100 dark:text-slate-800">{g.name}</h4><p className="text-sm text-slate-400 dark:text-gray-500">R$ {(g.currentAmount || 0).toFixed(2)} / R$ {(g.targetAmount || 0).toFixed(2)} (Progresso: {prog.toFixed(1)}%)</p></div><div className="flex space-x-2"><button onClick={() => openEditModal(g)} className="p-1 text-slate-400 hover:text-yellow-400 dark:text-gray-500 dark:hover:text-yellow-600"><Edit3 size={18} /></button><button onClick={() => handleDeleteGoal(g.id)} className="p-1 text-slate-400 hover:text-red-400 dark:text-gray-500 dark:hover:text-red-600"><Trash2 size={18} /></button></div></div><div className="w-full bg-slate-600 dark:bg-gray-300 rounded-full h-2.5 mt-2"><div className="bg-emerald-500 h-2.5 rounded-full" style={{ width: `${Math.min(prog, 100)}%` }}></div></div></div>);
            })}</div>
            <Modal isOpen={isModalOpen} onClose={() => { setIsModalOpen(false); setEditingGoal(null); setCustomError(''); }} title={editingGoal ? "Editar Meta" : "Nova Meta"}>
                <div className="space-y-4">
                    {customError && <p className="bg-red-500/20 text-red-400 p-3 text-sm">{customError}</p>}
                    <div><label htmlFor="goalName-form" className="block text-sm font-medium text-slate-300 dark:text-slate-700">Nome da Meta</label><input id="goalName-form" type="text" value={goalName} onChange={(e) => setGoalName(e.target.value)} className="mt-1 w-full p-3 bg-slate-700 rounded-lg dark:bg-gray-200 dark:text-slate-900" /></div>
                    <div><label htmlFor="goalTarget-form" className="block text-sm font-medium text-slate-300 dark:text-slate-700">Valor Alvo (R$)</label><input id="goalTarget-form" type="number" step="0.01" value={goalTargetAmount} onChange={(e) => setGoalTargetAmount(e.target.value)} className="mt-1 w-full p-3 bg-slate-700 rounded-lg dark:bg-gray-200 dark:text-slate-900" /></div>
                    <div><label htmlFor="goalCurrent-form" className="block text-sm font-medium text-slate-300 dark:text-slate-700">Valor Atual (R$)</label><input id="goalCurrent-form" type="number" step="0.01" value={goalCurrentAmount} onChange={(e) => setGoalCurrentAmount(e.target.value)} className="mt-1 w-full p-3 bg-slate-700 rounded-lg dark:bg-gray-200 dark:text-slate-900" /></div>
                    <div className="flex justify-end space-x-3 pt-4"><button type="button" onClick={() => { setIsModalOpen(false); setEditingGoal(null); setCustomError(''); }} className="px-6 py-3 bg-slate-600 rounded-lg dark:bg-gray-300 dark:text-slate-900">Cancelar</button><button type="button" onClick={handleSaveGoal} className="px-6 py-3 bg-emerald-600 dark:bg-emerald-700 text-white rounded-lg">Salvar</button></div>
                </div>
            </Modal>
        </div>
    );
};

const Dashboard = ({ user, handleLogout, theme, toggleTheme, isTelegramModalOpen, setIsTelegramModalOpen }) => {
    const [normalTransactions, setNormalTransactions] = useState([]);
    const [enrichedInstallmentPayments, setEnrichedInstallmentPayments] = useState([]);
    const [currentMonth, setCurrentMonth] = useState(new Date());
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingTransaction, setEditingTransaction] = useState(null);
    const [searchTerm, setSearchTerm] = useState('');
    const [transactionTypeFilter, setTransactionTypeFilter] = useState('all');
    const [activeTab, setActiveTab] = useState('dashboard'); // 'dashboard' or 'installments'

    const [loadingNormalTrans, setLoadingNormalTrans] = useState(true);
    const [loadingPayments, setLoadingPayments] = useState(true);
    const [globalLoading, setGlobalLoading] = useState(true);

    const [customError, setCustomError] = useState('');
    const [financialInsight, setFinancialInsight] = useState('');
    const [isLoadingInsight, setIsLoadingInsight] = useState(false);
    const [insightError, setInsightError] = useState('');

    useEffect(() => {
        if (user) {
            console.log("DEBUG: Current User ID CL:", user.uid);
            console.log("DEBUG: App ID CL:", appId);
        }
    }, [user]);

    const userId = user.uid;
    const transactionsPath = `artifacts/${appId}/users/${userId}/transactions`;
    const installmentsPath = `artifacts/${appId}/users/${userId}/installments`;
    const installmentPaymentsPath = `artifacts/${appId}/users/${userId}/installment_payments`;

    // Effect for normal transactions
    useEffect(() => {
        if (!userId) { setLoadingNormalTrans(false); return; }
        setLoadingNormalTrans(true);
        const q = query(collection(db, transactionsPath));
        const unsubscribe = onSnapshot(q, (snapshot) => {
            const fetched = snapshot.docs
                .map(d => ({ id: d.id, ...d.data() }))
                .filter(t => !t.isInstallmentOriginal);
            setNormalTransactions(fetched);
            setLoadingNormalTrans(false);
        }, (err) => {
            console.error("Error fetching normal transactions:", err);
            setCustomError("Falha ao carregar transações normais.");
            setLoadingNormalTrans(false);
        });
        return () => unsubscribe();
    }, [userId, transactionsPath]);

    // Effect for installment payments
    useEffect(() => {
        if (!userId) { setLoadingPayments(false); return; }
        setLoadingPayments(true);
        const q = query(collection(db, installmentPaymentsPath));
        const unsubscribe = onSnapshot(q, async (snapshot) => {
            const payments = snapshot.docs.map(d => ({
                id: d.id, ...d.data(),
                isInstallmentPayment: true,
                type: TRANSACTION_TYPES.EXPENSE
            }));

            let parentInstallmentsMap = new Map();
            const parentIds = [...new Set(payments.map(p => p.installmentId).filter(id => !!id))];
            if (parentIds.length > 0) {
                const idChunks = [];
                // Firebase `where(documentId(), "in", ...)` tem limite de 30.
                for (let i = 0; i < parentIds.length; i += 30) {
                    idChunks.push(parentIds.slice(i, i + 30));
                }
                try {
                    await Promise.all(idChunks.map(async (chunk) => {
                        if (chunk.length > 0) {
                            const parentsQuery = query(collection(db, installmentsPath), where(documentId(), "in", chunk));
                            const parentsSnapshot = await getDocs(parentsQuery);
                            parentsSnapshot.docs.forEach(doc => parentInstallmentsMap.set(doc.id, doc.data()));
                        }
                    }));
                } catch (err) {
                    console.error("Error fetching parent installments for payments:", err);
                    setCustomError("Falha ao buscar dados de parcelamentos pais.");
                }
            }
            const enriched = payments.map(p => {
                const parentData = parentInstallmentsMap.get(p.installmentId);
                return {
                    ...p,
                    description: `${parentData?.description || 'Compra Parcelada'} - Parcela ${p.paymentNumber || 'N/A'}/${p.totalInstallments || 'N/A'}`,
                    category: parentData?.category || 'Parcelamento',
                    // Adiciona 'amount' da parcela se não estiver presente (para compatibilidade com TransactionItem)
                    amount: p.amount || parentData?.valuePerInstallment || 0
                };
            });
            setEnrichedInstallmentPayments(enriched);
            setLoadingPayments(false);
        }, (err) => {
            console.error("Error fetching installment payments:", err);
            setCustomError("Falha ao carregar pagamentos de parcelas.");
            setLoadingPayments(false);
        });
        return () => unsubscribe();
    }, [userId, installmentPaymentsPath, installmentsPath]);

    const combinedTransactions = useMemo(() => {
        const all = [...normalTransactions, ...enrichedInstallmentPayments];
        return all.sort((a, b) => {
            const dateA = a.date?.toDate ? a.date.toDate().getTime() : 0;
            const dateB = b.date?.toDate ? b.date.toDate().getTime() : 0;
            return dateB - dateA;
        });
    }, [normalTransactions, enrichedInstallmentPayments]);

    useEffect(() => {
        setGlobalLoading(loadingNormalTrans || loadingPayments);
    }, [loadingNormalTrans, loadingPayments]);

    const filteredTransactions = useMemo(() => {
        return combinedTransactions.filter(t => {
            const tDateObj = t.date?.toDate ? t.date.toDate() : (t.date ? new Date(t.date) : null);
            if (!tDateObj || !isValid(tDateObj)) return false;
            const monthMatch = isSameMonth(tDateObj, currentMonth);
            const typeMatch = transactionTypeFilter === 'all' || t.type === transactionTypeFilter;
            const searchTermLower = searchTerm.toLowerCase();
            const searchMatch = (t.description && t.description.toLowerCase().includes(searchTermLower)) ||
                (t.category && t.category.toLowerCase().includes(searchTermLower));
            return monthMatch && typeMatch && searchMatch;
        });
    }, [combinedTransactions, currentMonth, searchTerm, transactionTypeFilter]);

    // Calcula o saldo total das transações filtradas
    const totalFilteredTransactionsAmount = useMemo(() => {
        return filteredTransactions.reduce((acc, transaction) => {
            if (transaction.type === TRANSACTION_TYPES.INCOME) {
                return acc + (transaction.amount || 0);
            } else if (transaction.type === TRANSACTION_TYPES.EXPENSE) {
                return acc - (transaction.amount || 0);
            }
            return acc;
        }, 0);
    }, [filteredTransactions]);


    const handleSaveTransaction = async (transactionData, transactionIdToEdit) => {
        if (!userId) return; setCustomError('');
        try {
            const isNewTransaction = !transactionIdToEdit;
            const isFormMarkedAsInstallment = transactionData.isInstallment;

            if (!isNewTransaction && editingTransaction) { // Editando
                let pathToUpdate = transactionsPath;
                let originalIsInstallmentMother = editingTransaction.isInstallmentOriginal || false;
                let originalIsInstallmentPayment = editingTransaction.isInstallmentPayment || false;

                if (originalIsInstallmentMother) {
                    pathToUpdate = installmentsPath;
                } else if (originalIsInstallmentPayment) {
                    pathToUpdate = installmentPaymentsPath;
                }

                const dataToUpdate = { ...transactionData };
                delete dataToUpdate.isInstallment; // Remove a flag de controle do form

                // Se era uma mãe e continua sendo, recalcula os valores totais/parcela
                if (originalIsInstallmentMother) {
                    // Aqui estamos no modo "edição de mãe parcelada". 
                    // No form, o amount é o valor da parcela.
                    dataToUpdate.totalAmount = dataToUpdate.amount * dataToUpdate.numberOfInstallments;
                    dataToUpdate.valuePerInstallment = dataToUpdate.amount;
                    dataToUpdate.isInstallmentOriginal = true;
                    // OBS: Esta lógica não atualiza as parcelas filhas no installment_payments, 
                    // o que é um ponto de complexidade. Mantemos a atualização da mãe para fins de relatório.
                } else { // Transação normal ou pagamento de parcela (só edita descrição/categoria/valor, mas valor é bloqueado no form para payments)
                    dataToUpdate.isInstallmentOriginal = false;
                }

                const transRef = doc(db, pathToUpdate, transactionIdToEdit);
                await updateDoc(transRef, dataToUpdate);

            } else { // Nova transação
                if (transactionData.isInstallment) { // Nova compra parcelada (mãe)
                    const installmentParentData = {
                        userId, description: transactionData.description,
                        totalAmount: transactionData.amount * transactionData.numberOfInstallments,
                        purchaseDate: transactionData.date,
                        numberOfInstallments: transactionData.numberOfInstallments,
                        category: transactionData.category, createdAt: Timestamp.now(),
                        valuePerInstallment: transactionData.amount,
                        isInstallmentOriginal: true
                    };
                    const installmentParentRef = await addDoc(collection(db, installmentsPath), installmentParentData);

                    for (let i = 0; i < transactionData.numberOfInstallments; i++) {
                        const dueDate = addMonths(transactionData.date.toDate(), i);
                        await addDoc(collection(db, installmentPaymentsPath), {
                            userId, installmentId: installmentParentRef.id,
                            paymentNumber: i + 1, totalInstallments: transactionData.numberOfInstallments,
                            amount: transactionData.amount, // amount é o valor da parcela
                            dueDate: Timestamp.fromDate(dueDate), isPaid: false,
                            date: Timestamp.fromDate(dueDate), type: TRANSACTION_TYPES.EXPENSE,
                        });
                    }
                } else { // Transação normal
                    await addDoc(collection(db, transactionsPath), { ...transactionData, userId, createdAt: Timestamp.now(), isInstallmentOriginal: false });
                }
            }
            setIsModalOpen(false); setEditingTransaction(null);
        } catch (err) { console.error("Erro ao salvar transação:", err); setCustomError("Falha ao salvar transação."); }
    };

    const handleDeleteTransaction = async (transactionToDelete) => {
        if (!userId || !transactionToDelete || !transactionToDelete.id) {
            alert("Erro: ID inválido ou usuário não logado.");
            return;
        }
        if (!window.confirm("Tem certeza que deseja excluir esta transação/parcelamento? Esta ação não pode ser desfeita.")) return;
        setCustomError('');
        try {
            if (transactionToDelete.isInstallmentPayment) {
                await deleteDoc(doc(db, installmentPaymentsPath, transactionToDelete.id));
            } else {
                if (transactionToDelete.isInstallmentOriginal) {
                    await deleteDoc(doc(db, installmentsPath, transactionToDelete.id));
                    const paymentsQuery = query(collection(db, installmentPaymentsPath), where("installmentId", "==", transactionToDelete.id));
                    const paymentsSnapshot = await getDocs(paymentsQuery);
                    await Promise.all(paymentsSnapshot.docs.map(d => deleteDoc(d.ref)));
                } else {
                    await deleteDoc(doc(db, transactionsPath, transactionToDelete.id));
                }
            }
        } catch (err) { console.error("Erro ao excluir:", err); setCustomError(`Falha ao excluir: ${err.message}`); }
    };

    const handleToggleInstallmentPaymentPaid = async (paymentId, newStatus) => {
        if (!userId) return; setCustomError('');
        try { await updateDoc(doc(db, installmentPaymentsPath, paymentId), { isPaid: newStatus, paidDate: newStatus ? Timestamp.now() : null }); }
        catch (error) { console.error(error); setCustomError("Falha ao atualizar status do pagamento."); }
    };

    const handleEditTransaction = (transaction) => {
        setCustomError('');
        if (transaction.isInstallmentPayment && !transaction.isInstallmentOriginal) {
            // Permite editar APENAS o status de pagamento
            setCustomError("Para alterar o status de pagamento de uma parcela, use o botão 'Pendente/Pago'. Para outras alterações, edite a descrição/categoria ou exclua.");
        }
        setEditingTransaction(transaction);
        setIsModalOpen(true);
    };



    const monthlySummary = useMemo(() => {
        const income = filteredTransactions.filter(t => t.type === TRANSACTION_TYPES.INCOME).reduce((sum, t) => sum + (t.amount || 0), 0);
        const expense = filteredTransactions.filter(t => t.type === TRANSACTION_TYPES.EXPENSE).reduce((sum, t) => sum + (t.amount || 0), 0);
        return { income, expense, balance: income - expense };
    }, [filteredTransactions]);

    // [REMOVED] Legacy Chart Data Memos (PieChart, Old Evolution)
    // Now using FinancialEvolutionChart which calculates its own evolution.

    const handleGenerateFinancialInsight = async () => {
        if (!GEMINI_API_KEY) { setInsightError("Chave da API Gemini não configurada."); setFinancialInsight(''); return; }
        setIsLoadingInsight(true); setInsightError(''); setFinancialInsight('');
        try {
            // Prepara um resumo simples dos dados para o LLM
            const insightPrompt = `Com base nas seguintes informações financeiras (Receita: R$${monthlySummary.income.toFixed(2)}, Despesa: R$${monthlySummary.expense.toFixed(2)} e as principais categorias de despesas: ${categoryDataForPieChart.map(c => `${c.name} (R$${c.value.toFixed(2)})`).join(', ')}), gere uma DICA financeira concisa (em português do Brasil) e motivacional para o usuário, com até 3 frases, focada em otimizar o orçamento atual.`;
            const insight = await callGeminiAPI(insightPrompt);
            if (insight) {
                setFinancialInsight(insight);
            } else {
                setInsightError("Não foi possível gerar a dica.");
            }
        } catch (error) {
            setInsightError(`Falha na IA: ${error.message}`);
            setFinancialInsight('');
        } finally {
            setIsLoadingInsight(false);
        }
    };

    return (
        <div className="min-h-screen bg-slate-950 text-slate-100 font-sans selection:bg-cyan-500/30">
            {/* Header / Top Bar in Glassmorphism */}
            <header className="sticky top-0 z-10 bg-slate-900/80 backdrop-blur-md border-b border-slate-800/50 p-4">
                <div className="flex justify-between items-center max-w-5xl mx-auto">
                    <div className="flex items-center space-x-3">
                        <button onClick={() => setCurrentMonth(subMonths(currentMonth, 1))} className="p-2 rounded-full hover:bg-slate-800 transition-colors bg-slate-800/50 border border-slate-700/50"><ChevronLeft size={20} className="text-cyan-400" /></button>
                        <h2 className="text-lg md:text-xl font-bold text-slate-100 capitalize tabular-nums">{format(currentMonth, 'MMMM yy', { locale: ptBR })}</h2>
                        <button onClick={() => setCurrentMonth(addMonths(currentMonth, 1))} className="p-2 rounded-full hover:bg-slate-800 transition-colors bg-slate-800/50 border border-slate-700/50"><ChevronRight size={20} className="text-cyan-400" /></button>
                    </div>

                    <div className="flex items-center space-x-3">
                        <button onClick={toggleTheme} className="p-2 rounded-full hover:bg-slate-800 text-slate-400 hover:text-yellow-400 transition-colors">
                            {theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />}
                        </button>
                        <button onClick={() => setIsTelegramModalOpen(true)} className="p-2 rounded-full hover:bg-slate-800 text-slate-400 hover:text-sky-400 transition-colors" title="Conectar Telegram">
                            <Send size={20} />
                        </button>
                        <button onClick={handleLogout} className="p-2 rounded-full hover:bg-slate-800 text-slate-400 hover:text-red-400 transition-colors"><LogOut size={20} /></button>
                    </div>
                </div>
            </header>

            <main className="max-w-md md:max-w-5xl mx-auto p-4 space-y-6 pb-24">

                {customError && (
                    <div className="p-4 bg-red-900/30 border border-red-500/30 rounded-2xl flex items-center justify-between backdrop-blur-sm">
                        <div className="flex items-center text-red-300 text-sm"><AlertTriangle size={18} className="mr-3" /><span>{customError}</span></div>
                        <button onClick={() => setCustomError('')} className="text-red-400 hover:text-red-200"><XCircle size={18} /></button>
                    </div>
                )}

                {/* Main Stats Cards - Horizontal Scroll on Mobile */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="bg-slate-800/40 border border-slate-700/50 backdrop-blur-xl p-5 rounded-3xl shadow-xl flex flex-col justify-between h-32 relative overflow-hidden group">
                        <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity"><TrendingUp size={64} className="text-green-500" /></div>
                        <span className="text-sm font-medium text-slate-400 uppercase tracking-wider">Receitas</span>
                        <span className="text-3xl font-bold text-green-400 tabular-nums">R$ {monthlySummary.income.toFixed(2)}</span>
                    </div>
                    <div className="bg-slate-800/40 border border-slate-700/50 backdrop-blur-xl p-5 rounded-3xl shadow-xl flex flex-col justify-between h-32 relative overflow-hidden group">
                        <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity"><TrendingUp size={64} className="text-red-500 rotate-180" /></div>
                        <span className="text-sm font-medium text-slate-400 uppercase tracking-wider">Despesas</span>
                        <span className="text-3xl font-bold text-rose-400 tabular-nums">R$ {monthlySummary.expense.toFixed(2)}</span>
                    </div>
                    <div className="bg-gradient-to-br from-cyan-600/20 to-blue-600/20 border border-cyan-500/30 backdrop-blur-xl p-5 rounded-3xl shadow-xl flex flex-col justify-between h-32 relative overflow-hidden">
                        <div className="absolute -bottom-4 -right-4 w-24 h-24 bg-cyan-500/30 blur-2xl rounded-full"></div>
                        <span className="text-sm font-medium text-cyan-200 uppercase tracking-wider">Saldo Mensal</span>
                        <span className={`text-3xl font-bold ${monthlySummary.balance >= 0 ? 'text-cyan-300' : 'text-rose-300'} tabular-nums`}>R$ {monthlySummary.balance.toFixed(2)}</span>
                    </div>
                </div>

                {/* TABS (Pill Shape) */}
                <div className="flex bg-slate-800/50 p-1 rounded-2xl mx-auto max-w-md border border-slate-700/50">
                    <button onClick={() => setActiveTab('dashboard')} className={`flex-1 py-2 px-3 rounded-xl text-xs md:text-sm font-medium transition-all duration-300 ${activeTab === 'dashboard' ? 'bg-cyan-500 text-white shadow-lg shadow-cyan-500/25' : 'text-slate-400 hover:text-slate-200'}`}>Visão Geral</button>
                    <button onClick={() => setActiveTab('installments')} className={`flex-1 py-2 px-3 rounded-xl text-xs md:text-sm font-medium transition-all duration-300 ${activeTab === 'installments' ? 'bg-violet-500 text-white shadow-lg shadow-violet-500/25' : 'text-slate-400 hover:text-slate-200'}`}>Parcelas</button>
                    <button onClick={() => setActiveTab('goals')} className={`flex-1 py-2 px-3 rounded-xl text-xs md:text-sm font-medium transition-all duration-300 ${activeTab === 'goals' ? 'bg-emerald-500 text-white shadow-lg shadow-emerald-500/25' : 'text-slate-400 hover:text-slate-200'}`}>Metas</button>
                </div>

                {activeTab === 'dashboard' && (
                    <div className="space-y-6 animate-fade-in-up">
                        {/* THE NEW CHARTS GRID */}
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                            <FinancialEvolutionChart transactions={filteredTransactions} currentMonth={currentMonth} />
                            <FinancialCategoryChart transactions={filteredTransactions} />
                        </div>

                        {/* Recent Transactions List */}
                        <div className="space-y-4">
                            <div className="flex items-center justify-between">
                                <h3 className="text-lg font-semibold text-slate-200">Transações Recentes</h3>
                                <button onClick={() => { setEditingTransaction(null); setIsModalOpen(true); }} className="bg-cyan-500 hover:bg-cyan-400 text-slate-900 rounded-full p-2 shadow-lg shadow-cyan-500/20 transition-transform active:scale-95"><PlusCircle size={24} /></button>
                            </div>

                            {/* Filters Small Row */}
                            <div className="flex space-x-2 overflow-x-auto pb-2 no-scrollbar">
                                <input type="text" placeholder="Buscar..." value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} className="bg-slate-800/50 border border-slate-700/50 rounded-xl px-4 py-2 text-sm text-slate-200 focus:outline-none focus:border-cyan-500/50 min-w-[150px]" />
                                <select value={transactionTypeFilter} onChange={(e) => setTransactionTypeFilter(e.target.value)} className="bg-slate-800/50 border border-slate-700/50 rounded-xl px-4 py-2 text-sm text-slate-200 focus:outline-none focus:border-cyan-500/50">
                                    <option value="all">Todas</option>
                                    <option value={TRANSACTION_TYPES.INCOME}>Receitas</option>
                                    <option value={TRANSACTION_TYPES.EXPENSE}>Despesas</option>
                                </select>
                            </div>

                            {/* Insight IA Card - Compact */}
                            <div className="bg-gradient-to-r from-violet-900/40 to-fuchsia-900/40 border border-violet-500/20 p-4 rounded-2xl flex items-start gap-4 backdrop-blur-sm">
                                <div className="p-2 bg-violet-500/20 rounded-xl shrink-0"><Zap size={20} className="text-violet-300" /></div>
                                <div className="flex-1">
                                    <h4 className="text-sm font-medium text-violet-200 mb-1">Dica Financeira IA</h4>
                                    {isLoadingInsight ? <p className="text-xs text-slate-400 animate-pulse">Consultando o oráculo...</p> :
                                        financialInsight ? <p className="text-xs text-slate-300 italic">"{financialInsight}"</p> :
                                            <button onClick={handleGenerateFinancialInsight} disabled={!GEMINI_API_KEY} className="text-xs text-violet-300 hover:text-white underline decoration-violet-500/50 underline-offset-2">Gerar análise agora</button>}
                                </div>
                            </div>

                            {globalLoading ? (
                                <div className="flex justify-center py-10"><Loader2 className="animate-spin text-cyan-500" size={32} /></div>
                            ) : filteredTransactions.length === 0 ? (
                                <div className="text-center py-10 text-slate-500 bg-slate-800/30 rounded-3xl border border-slate-700/30 border-dashed">
                                    <p>Nenhuma transação encontrada.</p>
                                </div>
                            ) : (
                                <div className="space-y-3 pb-safe">
                                    {filteredTransactions.map(transaction => (
                                        <TransactionItem key={transaction.id} transaction={transaction} onEdit={handleEditTransaction} onDelete={handleDeleteTransaction} onTogglePaid={handleToggleInstallmentPaymentPaid} />
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {activeTab === 'installments' && (
                    <div className="space-y-6 animate-fade-in-up">
                        <InstallmentsReport userId={userId} showAll={true} onEdit={handleEditTransaction} onDelete={handleDeleteTransaction} />
                    </div>
                )}

                {activeTab === 'goals' && (
                    <div className="space-y-6 animate-fade-in-up">
                        <GoalsSection userId={userId} />
                    </div>
                )}
            </main>

            <TransactionForm isOpen={isModalOpen} onClose={() => { setIsModalOpen(false); setEditingTransaction(null); }} onSave={handleSaveTransaction} editingTransaction={editingTransaction} currentMonth={currentMonth} />

            {/* Telegram Connect Modal */}
            <Modal isOpen={isTelegramModalOpen} onClose={() => setIsTelegramModalOpen(false)} title="Conectar Telegram">
                <div className="space-y-6 text-center">
                    <div className="bg-sky-500/20 p-4 rounded-full w-20 h-20 mx-auto flex items-center justify-center">
                        <Send size={40} className="text-sky-400" />
                    </div>
                    <div>
                        <p className="text-slate-300 dark:text-slate-600 mb-2">Para usar o bot, envie o comando abaixo para o nosso bot no Telegram:</p>
                        <div className="bg-slate-800 dark:bg-slate-200 p-4 rounded-xl border border-slate-700/50 dark:border-slate-300 flex items-center justify-between">
                            <code className="text-sky-400 dark:text-sky-700 font-mono text-lg">/start {userId}</code>
                            <button onClick={() => navigator.clipboard.writeText(`/start ${userId}`)} className="p-2 hover:bg-slate-700 dark:hover:bg-slate-300 rounded-lg transition-colors text-slate-400 dark:text-slate-600">
                                <Copy size={20} />
                            </button>
                        </div>

                        <div className="mt-4">
                            <a href={`https://t.me/controlr8_bot?start=${userId}`} target="_blank" rel="noopener noreferrer" className="inline-flex items-center px-6 py-3 bg-sky-600 hover:bg-sky-500 text-white font-semibold rounded-lg transition-colors">
                                <Send size={18} className="mr-2" />
                                Conectar Agora
                            </a>
                        </div>
                    </div>
                    <p className="text-xs text-slate-500 dark:text-slate-400">Isso vinculará seu usuário do Telegram à sua conta aqui no app.</p>
                </div>
            </Modal>
        </div>
    );
};

export default function App() {
    const [user, setUser] = useState(null);
    const [loadingAuth, setLoadingAuth] = useState(true);
    const [isAuthReady, setIsAuthReady] = useState(false);
    const [isTelegramModalOpen, setIsTelegramModalOpen] = useState(false); // Telegram Modal State
    const [theme, setTheme] = useState(localStorage.getItem('theme') || 'dark'); // Estado do tema

    const toggleTheme = useCallback(() => {
        setTheme(prev => {
            const newTheme = prev === 'dark' ? 'light' : 'dark';
            localStorage.setItem('theme', newTheme);
            return newTheme;
        });
    }, []);

    useEffect(() => {
        // Aplica a classe ao elemento <html> para que o Tailwind possa usar o modificador `dark:`
        if (theme === 'dark') {
            document.documentElement.classList.add('dark');
        } else {
            document.documentElement.classList.remove('dark');
        }
    }, [theme]);


    useEffect(() => {
        const initFirebaseAuth = async () => {
            try { if (initialAuthToken) { await signInWithCustomToken(auth, initialAuthToken); } }
            catch (error) { console.error("Erro auth token:", error); }
        };
        initFirebaseAuth();
        const unsubscribe = onAuthStateChanged(auth, (currentUser) => { setUser(currentUser); setLoadingAuth(false); setIsAuthReady(true); });
        return () => unsubscribe();
    }, []);
    const handleLogout = async () => { try { await signOut(auth); setUser(null); } catch (error) { console.error("Erro logout:", error); } };

    if (loadingAuth || !isAuthReady) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-slate-900 dark:bg-gray-100">
                <div className="text-center">
                    <svg className="animate-spin h-12 w-12 text-cyan-500 dark:text-cyan-700 mx-auto mb-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                    <p className="text-xl text-slate-300 dark:text-slate-800">Carregando...</p>
                </div>
            </div>
        );
    }

    if (!user) { return <AuthComponent setUser={setUser} />; }

    return <Dashboard
        user={user}
        handleLogout={handleLogout}
        theme={theme}
        toggleTheme={toggleTheme}
        isTelegramModalOpen={isTelegramModalOpen}
        setIsTelegramModalOpen={setIsTelegramModalOpen}
    />;
}